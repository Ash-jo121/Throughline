from __future__ import annotations

import asyncio
from typing import Any
from uuid import uuid4

from throughline.memory import recall_related, remember_ticket
from throughline.store import persist_brief, persist_customer_data
from throughline.synthesize import IncidentBrief, synthesize_brief
from throughline.tickets import normalize_ticket, ticket_recall_query


async def build_incident_brief(ticket: dict[str, Any]) -> IncidentBrief:
    """Run Day 2 orchestration without remembering the incoming ticket yet."""

    normalized = normalize_ticket(ticket)
    session_id = f"sess_{uuid4()}"
    recall_output = await recall_related(ticket_recall_query(normalized), session_id=session_id)
    recall_text = getattr(recall_output, "text", str(recall_output))
    brief = await synthesize_brief(normalized, recall_text)
    persist_brief(
        brief,
        session_id=getattr(recall_output, "session_id", session_id),
        qa_id=getattr(recall_output, "qa_id", None),
    )
    return brief


async def remember_ticket_background(ticket: dict[str, Any]) -> None:
    normalized = normalize_ticket(ticket)
    data_ids = await remember_ticket(normalized)
    for data_id in data_ids:
        persist_customer_data(
            normalized["customer"]["name"],
            data_id,
            source_ref=normalized["id"],
        )


def schedule_ticket_memory(ticket: dict[str, Any]) -> None:
    asyncio.create_task(remember_ticket_background(ticket))
