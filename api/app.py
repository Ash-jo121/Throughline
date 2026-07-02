from __future__ import annotations

from typing import Literal

from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from throughline.resolve import resolve_customer
from throughline.service import build_incident_brief, remember_ticket_background
from throughline.store import get_brief, persist_feedback, persist_forget_request
from throughline.synthesize import IncidentBrief


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
def create_feedback(brief_id: str, feedback: FeedbackRequest) -> dict[str, str]:
    if get_brief(brief_id) is None:
        raise HTTPException(status_code=404, detail="Brief not found")
    feedback_id = persist_feedback(brief_id, feedback.verdict, feedback.note)
    return {"feedback_id": feedback_id, "status": "stored"}


@app.post("/customers/{name}/forget")
def request_customer_forget(name: str) -> dict[str, str]:
    request_id = persist_forget_request(resolve_customer(name))
    return {"request_id": request_id, "status": "pending"}
