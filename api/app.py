from __future__ import annotations

import asyncio
import json
import os
from typing import Literal
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from throughline.jira import (
    JiraConfigurationError,
    JiraRequestError,
    fetch_jira_issue,
    jira_configured,
    jira_issue_to_ticket,
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
    get_brief,
    get_brief_memory_refs,
    list_customer_data_ids,
    mark_customer_data_forgotten,
    mark_forget_request_done,
    persist_feedback,
    persist_forget_request,
)
from throughline.synthesize import IncidentBrief


app = FastAPI(title="Throughline", version="0.2.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
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
    brief: IncidentBrief


class JiraImportResponse(BaseModel):
    issue_key: str
    ticket: dict
    brief_id: str
    brief: IncidentBrief


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
    "/incidents",
    response_model=IncidentResponse,
    summary="Create an incident brief from an incoming ticket",
)
async def create_incident_brief(
    incident: IncidentRequest,
    background_tasks: BackgroundTasks,
) -> IncidentResponse:
    ticket = incident.model_dump()
    brief = await build_incident_brief(ticket)
    background_tasks.add_task(remember_ticket_background, ticket)
    return IncidentResponse(brief_id=brief.brief_id, brief=brief)


@app.get("/integrations/jira/issues/{issue_key}")
def read_jira_issue(issue_key: str) -> dict:
    try:
        return fetch_jira_issue(issue_key)
    except JiraConfigurationError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except JiraRequestError as error:
        raise HTTPException(status_code=502, detail=str(error)) from error


@app.post("/integrations/jira/issues/{issue_key}/brief", response_model=JiraImportResponse)
async def create_brief_from_jira(
    issue_key: str,
    background_tasks: BackgroundTasks,
) -> JiraImportResponse:
    try:
        issue = fetch_jira_issue(issue_key)
    except JiraConfigurationError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except JiraRequestError as error:
        raise HTTPException(status_code=502, detail=str(error)) from error

    ticket = jira_issue_to_ticket(issue)
    brief = await build_incident_brief(ticket)
    background_tasks.add_task(remember_ticket_background, ticket)
    return JiraImportResponse(
        issue_key=str(issue.get("key") or issue_key),
        ticket=ticket,
        brief_id=brief.brief_id,
        brief=brief,
    )


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
    request = Request(
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
