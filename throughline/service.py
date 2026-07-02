from __future__ import annotations

import asyncio
from typing import Any

from throughline.memory import recall_related, remember_ticket
from throughline.store import persist_brief
from throughline.synthesize import IncidentBrief, synthesize_brief
from throughline.tickets import normalize_ticket, ticket_recall_query


async def build_incident_brief(ticket: dict[str, Any]) -> IncidentBrief:
    """Run Day 2 orchestration without remembering the incoming ticket yet."""

    normalized = normalize_ticket(ticket)
    recall_output = await recall_related(ticket_recall_query(normalized))
    brief = await synthesize_brief(normalized, recall_output)
    persist_brief(brief)
    return brief


async def remember_ticket_background(ticket: dict[str, Any]) -> None:
    await remember_ticket(normalize_ticket(ticket))


def schedule_ticket_memory(ticket: dict[str, Any]) -> None:
    asyncio.create_task(remember_ticket_background(ticket))
