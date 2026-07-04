from __future__ import annotations

from typing import Literal

from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from throughline.resolve import resolve_customer
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
from throughline.memory import forget_customer_data, improve_from_feedback


app = FastAPI(title="Throughline", version="0.2.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
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
