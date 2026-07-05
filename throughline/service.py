from __future__ import annotations

import asyncio
import os
import re
from typing import Any
from uuid import uuid4

from throughline.memory import recall_related, remember_ticket
from throughline.store import persist_brief, persist_customer_data
from throughline.synthesize import IncidentBrief, SourceLink, synthesize_brief
from throughline.tickets import normalize_ticket, ticket_recall_query


async def build_incident_brief(ticket: dict[str, Any]) -> IncidentBrief:
    """Run Day 2 orchestration without remembering the incoming ticket yet."""

    normalized = normalize_ticket(ticket)
    session_id = f"sess_{uuid4()}"
    recall_output = await recall_related(ticket_recall_query(normalized), session_id=session_id)
    recall_text = getattr(recall_output, "text", str(recall_output))
    brief = await synthesize_brief(normalized, recall_text)
    brief.source_links = _source_links(normalized, recall_text, brief)
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


def _source_links(
    ticket: dict[str, Any],
    recall_text: str,
    brief: IncidentBrief,
) -> list[SourceLink]:
    links: list[SourceLink] = []
    jira_base = os.getenv("JIRA_SITE_URL", "").rstrip("/")
    issue_key = ticket["id"]
    if jira_base and issue_key:
        links.append(
            SourceLink(
                label=f"Jira {issue_key}",
                url=f"{jira_base}/browse/{issue_key}",
                kind="jira",
            )
        )

    pr_number = _first_pr_number(" ".join([recall_text, brief.recommended_fix]))
    if pr_number:
        links.append(
            SourceLink(
                label=f"PR #{pr_number}",
                url=f"https://github.com/acme/payments/pull/{pr_number}",
                kind="pull_request",
            )
        )

    sentry = ticket.get("sentry_error") or {}
    error_class = sentry.get("error_class")
    if error_class:
        links.append(
            SourceLink(
                label=f"Sentry {error_class}",
                url=f"https://sentry.io/organizations/acme/issues/?query={error_class}",
                kind="sentry",
            )
        )

    return links


def _first_pr_number(text: str) -> str | None:
    match = re.search(r"\bPR\s*#?\s*(\d+)\b", text, flags=re.IGNORECASE)
    return match.group(1) if match else None
