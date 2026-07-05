from __future__ import annotations

import asyncio
import logging
import os
import re
from typing import Any
from urllib.parse import quote
from uuid import uuid4

from throughline.memory import recall_related, remember_ticket
from throughline.store import persist_brief, persist_customer_data
from throughline.synthesize import IncidentBrief, SourceLink, synthesize_brief
from throughline.tickets import normalize_ticket, ticket_recall_query

logger = logging.getLogger(__name__)

REFERENCE_PATTERN = r"\b(?:INC-\d{4}-\d{2}|[A-Z][A-Z0-9]+-\d+)\b"


async def build_incident_brief(ticket: dict[str, Any]) -> IncidentBrief:
    """Run Day 2 orchestration without remembering the incoming ticket yet."""

    normalized = normalize_ticket(ticket)
    session_id = f"sess_{uuid4()}"
    recall_output = await recall_related(ticket_recall_query(normalized), session_id=session_id)
    recall_text = getattr(recall_output, "text", str(recall_output))
    brief = await synthesize_brief(normalized, recall_text)
    _sanitize_brief(brief, normalized, recall_text)
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
    logger.info(
        "Remembered ticket %s for customer %s with data_ids=%s",
        normalized["id"],
        normalized["customer"]["name"],
        data_ids,
    )
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
    source_url = ticket.get("source_url")
    issue_key = ticket["id"]
    jira_base = os.getenv("JIRA_SITE_URL", "").rstrip("/")
    if source_url:
        links.append(SourceLink(label=f"Jira {issue_key}", url=str(source_url), kind="jira"))
    elif jira_base and issue_key:
        links.append(
            SourceLink(
                label=f"Jira {issue_key}",
                url=f"{jira_base}/browse/{issue_key}",
                kind="jira",
            )
        )

    pr_number = _first_pr_number(" ".join([recall_text, brief.recommended_fix]))
    if pr_number and brief.matched_incident_id:
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
        query = quote(str(error_class))
        links.append(
            SourceLink(
                label=f"Sentry {error_class}",
                url=f"https://sentry.io/organizations/acme/issues/?query={query}",
                kind="sentry",
            )
        )

    return links


def _first_pr_number(text: str) -> str | None:
    match = re.search(r"\bPR\s*#?\s*(\d+)\b", text, flags=re.IGNORECASE)
    return match.group(1) if match else None


def _sanitize_brief(
    brief: IncidentBrief,
    ticket: dict[str, Any],
    recall_text: str,
) -> None:
    recall_refs = _candidate_refs(recall_text, exclude=str(ticket.get("id") or ""))
    accepted_refs = [ref for ref in recall_refs if _candidate_shares_ticket_signal(ref, ticket, recall_text)]

    if brief.matched_incident_id not in accepted_refs:
        replacement = accepted_refs[0] if accepted_refs else None
        brief.matched_incident_id = replacement

    if not brief.matched_incident_id:
        brief.matched_incident_id = None

    if not brief.matched_incident_id:
        brief.related = []
        brief.also_affected = []
        brief.confidence = "low"
    else:
        related = [ref for ref in brief.related if ref in accepted_refs]
        if brief.matched_incident_id not in related:
            related.insert(0, brief.matched_incident_id)
        brief.related = related

    assignee = ticket.get("assignee")
    if assignee:
        brief.suggested_owner = str(assignee)


def _candidate_refs(recall_text: str, *, exclude: str) -> list[str]:
    seen: set[str] = set()
    refs: list[str] = []
    for match in re.finditer(REFERENCE_PATTERN, recall_text):
        ref = match.group(0).upper()
        if ref == exclude.upper() or ref in seen:
            continue
        seen.add(ref)
        refs.append(ref)
    return refs


def _candidate_shares_ticket_signal(ref: str, ticket: dict[str, Any], recall_text: str) -> bool:
    contexts = _contexts_for_ref(ref, recall_text)
    component = str(ticket.get("component") or "").lower()
    sentry = ticket.get("sentry_error") or {}
    error_class = str(sentry.get("error_class") or "").lower()
    for context in contexts:
        lowered = context.lower()
        if component and component in lowered:
            return True
        if error_class and error_class in lowered:
            return True
    return False


def _contexts_for_ref(ref: str, recall_text: str) -> list[str]:
    escaped = re.escape(ref)
    chunks = [
        chunk.strip()
        for chunk in re.split(r"(?:\n{2,}|(?<=[.!?])\s+)", recall_text)
        if re.search(escaped, chunk, flags=re.IGNORECASE)
    ]
    if chunks:
        return chunks

    contexts: list[str] = []
    for match in re.finditer(escaped, recall_text, flags=re.IGNORECASE):
        start = max(0, match.start() - 240)
        end = min(len(recall_text), match.end() + 240)
        contexts.append(recall_text[start:end])
    return contexts
