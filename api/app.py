from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Literal
from urllib.error import HTTPError, URLError
from urllib.request import Request as UrlRequest
from urllib.request import urlopen

from fastapi import BackgroundTasks, FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from throughline.jira import (
    JiraConfigurationError,
    JiraIssueNotFound,
    JiraRequestError,
    fetch_jira_issue,
    jira_configured,
    jira_issue_to_ticket,
    jira_missing_env_vars,
)
from throughline.memory import (
    forget_customer_data,
    improve_from_feedback,
    remember_incident,
    reset_memory,
)
from throughline.resolve import resolve_customer
from throughline.seed import PAST_INCIDENTS
from throughline.service import build_incident_brief, remember_ticket_background
from throughline.store import (
    get_all_briefs,
    get_brief,
    get_brief_memory_refs,
    get_latest_brief,
    list_customer_data_ids,
    mark_customer_data_forgotten,
    mark_forget_request_done,
    persist_feedback,
    persist_forget_request,
)
from throughline.synthesize import IncidentBrief


app = FastAPI(title="Throughline", version="0.2.0")
logger = logging.getLogger(__name__)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:5174",
        "http://127.0.0.1:5174",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class IncidentRequest(BaseModel):
    id: str
    raw_customer: str
    component: str
    summary: str
    date: str = ""
    sentry_error: dict | None = None


class IncidentResponse(BaseModel):
    brief_id: str
    brief_path: str
    brief_url: str
    brief: IncidentBrief


class JiraImportResponse(BaseModel):
    issue_key: str
    ticket: dict
    brief_id: str
    brief_path: str
    brief_url: str
    brief: IncidentBrief


class WebhookAcceptedResponse(BaseModel):
    status: str
    issue_key: str | None = None


class FeedbackRequest(BaseModel):
    verdict: Literal["up", "down"]
    note: str | None = None


class FeedbackResponse(BaseModel):
    feedback_id: str
    status: str
    improve_scope: str


class ForgetResponse(BaseModel):
    request_id: str
    status: str
    forgotten_count: int


def _brief_path(brief_id: str) -> str:
    return f"/brief/{brief_id}"


def _brief_url(brief_id: str) -> str:
    public_base = os.getenv("THROUGHLINE_PUBLIC_BASE_URL", "http://localhost:5173").rstrip("/")
    return f"{public_base}{_brief_path(brief_id)}"


def _incident_response(brief: IncidentBrief) -> IncidentResponse:
    return IncidentResponse(
        brief_id=brief.brief_id,
        brief_path=_brief_path(brief.brief_id),
        brief_url=_brief_url(brief.brief_id),
        brief=brief,
    )


def _jira_import_response(issue_key: str, ticket: dict, brief: IncidentBrief) -> JiraImportResponse:
    return JiraImportResponse(
        issue_key=issue_key,
        ticket=ticket,
        brief_id=brief.brief_id,
        brief_path=_brief_path(brief.brief_id),
        brief_url=_brief_url(brief.brief_id),
        brief=brief,
    )


async def _brief_from_existing_ticket(
    incident: IncidentRequest,
    background_tasks: BackgroundTasks,
) -> IncidentResponse:
    ticket = incident.model_dump()
    brief = await build_incident_brief(ticket)
    background_tasks.add_task(remember_ticket_background, ticket)
    return _incident_response(brief)


async def _brief_from_jira_issue_key(
    issue_key: str,
    background_tasks: BackgroundTasks,
) -> JiraImportResponse:
    try:
        issue = fetch_jira_issue(issue_key)
    except JiraConfigurationError as error:
        missing = ", ".join(jira_missing_env_vars())
        detail = f"{error}. Set {missing}." if missing else str(error)
        raise HTTPException(status_code=400, detail=detail) from error
    except JiraIssueNotFound as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except JiraRequestError as error:
        raise HTTPException(status_code=502, detail=str(error)) from error

    ticket = jira_issue_to_ticket(issue)
    brief = await build_incident_brief(ticket)
    background_tasks.add_task(remember_ticket_background, ticket)
    return _jira_import_response(str(issue.get("key") or issue_key), ticket, brief)


async def _generate_jira_brief_background(issue_key: str) -> None:
    try:
        issue = fetch_jira_issue(issue_key)
        ticket = jira_issue_to_ticket(issue)
        await build_incident_brief(ticket)
        await remember_ticket_background(ticket)
    except Exception:
        logger.exception("Jira webhook brief generation failed for issue %s", issue_key)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/integrations")
def integrations() -> dict[str, dict[str, bool | str]]:
    return {
        "jira": {
            "configured": jira_configured(),
            "auth": "Jira Cloud Basic auth with email + API token",
        },
        "slack": {
            "configured": bool(os.getenv("SLACK_WEBHOOK_URL")),
            "auth": "Incoming webhook URL",
        },
    }


@app.post(
    "/integrations/jira/issues",
    response_model=IncidentResponse,
    summary="Generate an incident brief from an existing Jira issue",
)
async def receive_jira_issue(
    incident: IncidentRequest,
    background_tasks: BackgroundTasks,
) -> IncidentResponse:
    return await _brief_from_existing_ticket(incident, background_tasks)


@app.get("/integrations/jira/issues/{issue_key}")
def read_jira_issue(issue_key: str) -> dict:
    try:
        return fetch_jira_issue(issue_key)
    except JiraConfigurationError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except JiraIssueNotFound as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except JiraRequestError as error:
        raise HTTPException(status_code=502, detail=str(error)) from error


@app.post(
    "/integrations/jira/issues/{issue_key}/brief",
    response_model=JiraImportResponse,
    summary="Import a Jira issue by key and generate an incident brief",
)
async def import_jira_issue_by_key(
    issue_key: str,
    background_tasks: BackgroundTasks,
) -> JiraImportResponse:
    return await _brief_from_jira_issue_key(issue_key, background_tasks)


@app.post(
    "/integrations/jira/webhook",
    response_model=WebhookAcceptedResponse,
    summary="Receive Jira issue-created webhooks and generate briefs asynchronously",
)
async def receive_jira_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    secret: str | None = None,
    x_jira_webhook_secret: str | None = Header(default=None),
) -> WebhookAcceptedResponse:
    configured_secret = os.getenv("JIRA_WEBHOOK_SECRET")
    if configured_secret and configured_secret not in {secret, x_jira_webhook_secret}:
        raise HTTPException(status_code=401, detail="Invalid Jira webhook secret.")

    try:
        payload = await request.json()
    except Exception as error:
        raise HTTPException(status_code=400, detail="Webhook body must be valid JSON.") from error

    event_name = payload.get("webhookEvent")
    if event_name != "jira:issue_created":
        return WebhookAcceptedResponse(status="ignored")

    issue_key = ((payload.get("issue") or {}).get("key") or "").strip()
    if not issue_key:
        raise HTTPException(status_code=400, detail="Jira webhook payload is missing issue.key.")

    if not jira_configured():
        logger.warning(
            "Accepted Jira webhook for %s, but Jira REST is not configured. Missing: %s",
            issue_key,
            ", ".join(jira_missing_env_vars()),
        )

    background_tasks.add_task(_generate_jira_brief_background, issue_key)
    return WebhookAcceptedResponse(status="accepted", issue_key=issue_key)


@app.post(
    "/incidents",
    response_model=IncidentResponse,
    summary="Generate an incident brief from an incoming ticket",
    include_in_schema=False,
)
async def create_incident_brief(
    incident: IncidentRequest,
    background_tasks: BackgroundTasks,
) -> IncidentResponse:
    return await _brief_from_existing_ticket(incident, background_tasks)


@app.get("/briefs/latest", response_model=IncidentBrief)
def read_latest_brief() -> IncidentBrief:
    brief = get_latest_brief()
    if brief is None:
        raise HTTPException(status_code=404, detail="Brief not found")
    return brief


@app.get("/briefs", response_model=list[IncidentBrief])
def list_briefs() -> list[IncidentBrief]:
    return get_all_briefs()


@app.get("/briefs/{brief_id}", response_model=IncidentBrief)
def read_brief(brief_id: str) -> IncidentBrief:
    brief = get_brief(brief_id)
    if brief is None:
        raise HTTPException(status_code=404, detail="Brief not found")
    return brief


@app.post("/briefs/{brief_id}/feedback")
async def create_feedback(brief_id: str, feedback: FeedbackRequest) -> FeedbackResponse:
    if get_brief(brief_id) is None:
        raise HTTPException(status_code=404, detail="Brief not found")
    feedback_id = persist_feedback(brief_id, feedback.verdict, feedback.note)
    refs = get_brief_memory_refs(brief_id)
    improve_result = await improve_from_feedback(
        session_id=refs.session_id if refs else None,
        qa_id=refs.qa_id if refs else None,
        verdict=feedback.verdict,
        note=feedback.note,
    )
    return FeedbackResponse(
        feedback_id=feedback_id,
        status="stored_and_improved",
        improve_scope=str(improve_result["improve_scope"]),
    )


@app.post("/customers/{name}/forget")
async def request_customer_forget(name: str) -> ForgetResponse:
    customer_name = resolve_customer(name)
    request_id = persist_forget_request(customer_name)
    data_ids = list_customer_data_ids(customer_name)
    if data_ids:
        await forget_customer_data(data_ids)
        mark_customer_data_forgotten(customer_name, data_ids)
    detail = f"forget completed for {len(data_ids)} customer-owned data item(s)"
    mark_forget_request_done(request_id, detail)
    return ForgetResponse(request_id=request_id, status="done", forgotten_count=len(data_ids))


@app.post("/briefs/{brief_id}/share/slack")
def share_brief_to_slack(brief_id: str) -> dict[str, str]:
    brief = get_brief(brief_id)
    if brief is None:
        raise HTTPException(status_code=404, detail="Brief not found")

    webhook_url = os.getenv("SLACK_WEBHOOK_URL", "").strip()
    if not webhook_url:
        raise HTTPException(status_code=400, detail="Set SLACK_WEBHOOK_URL to enable Slack share.")

    message = {
        "text": (
            f"*{brief.title}*\n"
            f"Customer: {brief.customer} | Component: {brief.component} | "
            f"Matched: {brief.matched_incident_id or 'none'}\n"
            f"Recommended fix: {brief.recommended_fix}"
        )
    }
    request = UrlRequest(
        webhook_url,
        data=json.dumps(message).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=20) as response:
            if response.status >= 300:
                raise HTTPException(status_code=502, detail=f"Slack returned {response.status}")
    except HTTPError as error:
        raise HTTPException(status_code=502, detail=f"Slack returned {error.code}") from error
    except URLError as error:
        raise HTTPException(
            status_code=502, detail=f"Could not reach Slack: {error.reason}"
        ) from error

    return {"status": "shared"}


@app.post("/demo/reset")
async def reset_demo_memory() -> dict[str, str]:
    await reset_memory()
    return {"status": "reset"}


@app.post("/demo/backfill")
async def backfill_demo_memory() -> dict[str, str]:
    await reset_memory()
    for incident in PAST_INCIDENTS:
        await remember_incident(incident)
        await asyncio.sleep(0)
    return {"status": "backfilled", "count": str(len(PAST_INCIDENTS))}
