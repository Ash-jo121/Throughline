from __future__ import annotations

import json
import logging
import os
import re
from datetime import UTC, datetime
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field, ValidationError

from throughline.config import configure_environment
from throughline.tickets import normalize_ticket

configure_environment()

logger = logging.getLogger(__name__)

REFERENCE_PATTERN = r"\b(?:INC-\d{4}-\d{2}|[A-Z][A-Z0-9]+-\d+)\b"


class SourceLink(BaseModel):
    label: str
    url: str
    kind: Literal["jira", "pull_request", "sentry", "other"] = "other"


class IncidentBrief(BaseModel):
    brief_id: str = Field(default_factory=lambda: str(uuid4()))
    incident_ref: str
    customer: str
    component: str
    title: str
    probable_cause: str
    matched_incident_id: str | None = None
    why_related: str
    recommended_fix: str
    suggested_owner: str | None = None
    also_affected: list[str] = Field(default_factory=list)
    confidence: Literal["high", "medium", "low"]
    related: list[str] = Field(default_factory=list)
    source_links: list[SourceLink] = Field(default_factory=list)
    generated_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())


async def synthesize_brief(ticket: dict[str, Any], recall_output: str) -> IncidentBrief:
    """Synthesize a shareable incident brief from the incoming ticket and graph recall."""

    normalized = normalize_ticket(ticket)
    if os.getenv("LLM_API_KEY"):
        try:
            return await _synthesize_with_llm(normalized, recall_output)
        except (json.JSONDecodeError, ValidationError, ValueError) as error:
            logger.warning(
                "LLM brief synthesis returned invalid structured output; using deterministic "
                "fallback.",
                exc_info=error,
            )

    return _synthesize_deterministic(normalized, recall_output)


async def _synthesize_with_llm(ticket: dict[str, Any], recall_output: str) -> IncidentBrief:
    from openai import AsyncOpenAI

    client = AsyncOpenAI(api_key=os.environ["LLM_API_KEY"])
    response = await client.responses.parse(
        model=os.getenv("THROUGHLINE_SYNTH_MODEL", "gpt-4.1-mini"),
        input=[
            {
                "role": "system",
                "content": (
                    "You write concise incident briefs from an incoming support ticket and "
                    "Cognee graph recall. Use only facts present in the ticket or recall. "
                    "Do not invent PR numbers, engineers, customers, or incident ids. "
                    "Set matched_incident_id only when the recalled past incident or ticket "
                    "shares the same component as the incoming ticket, or the same exact "
                    "specific error entity. Do not match merely because two records contain "
                    "generic words like timeout, error, failure, retry, or backoff. If no "
                    "prior record shares the component or exact error entity, set "
                    "matched_incident_id to null, related to [], confidence to low, and "
                    "explain that no graph-safe match was found. Jira issue keys such as "
                    "KAN-5 are valid matched_incident_id values when recall supports them. "
                    "Return a complete IncidentBrief. Use null for unknown optional fields."
                ),
            },
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "ticket": ticket,
                        "recall_output": recall_output,
                        "schema": IncidentBrief.model_json_schema(),
                    }
                ),
            },
        ],
        text_format=IncidentBrief,
    )
    if response.output_parsed is None:
        raise ValueError("OpenAI returned no parsed IncidentBrief")
    return response.output_parsed


def _synthesize_deterministic(ticket: dict[str, Any], recall_output: str) -> IncidentBrief:
    """Best-effort parser used when the LLM is unavailable or returns invalid JSON.

    It intentionally extracts from the recall text instead of baking in the demo incident, so it
    remains a useful degraded path beyond the PaymentService fixture.
    """

    recall = recall_output or ""
    related = _reference_ids(recall, exclude=ticket["id"])
    matched_incident_id = related[0] if related else None
    pr_ref = _first_match(r"\bPR\s*#?\s*\d+\b", recall)
    owner = _extract_owner(recall)
    also_affected = _extract_customer_list(recall)
    recommended_fix = _extract_fix(recall, pr_ref)
    probable_cause = _extract_probable_cause(recall)
    why_related = _explain_relation(ticket, recall, matched_incident_id)
    confidence = _confidence(matched_incident_id, pr_ref, recall)

    return IncidentBrief(
        incident_ref=ticket["id"],
        customer=ticket["customer"]["name"],
        component=ticket["component"],
        title=f"{ticket['component']} escalation for {ticket['customer']['name']}",
        probable_cause=probable_cause,
        matched_incident_id=matched_incident_id,
        why_related=why_related,
        recommended_fix=recommended_fix,
        suggested_owner=owner,
        also_affected=also_affected,
        confidence=confidence,
        related=related,
    )


def _first_match(pattern: str, text: str) -> str | None:
    match = re.search(pattern, text, flags=re.IGNORECASE)
    if not match:
        return None
    return re.sub(r"\s+", " ", match.group(0)).replace("PR #", "PR #")


def _reference_ids(text: str, *, exclude: str) -> list[str]:
    seen: set[str] = set()
    refs: list[str] = []
    for match in re.finditer(REFERENCE_PATTERN, text):
        ref = match.group(0).upper()
        if ref == exclude.upper() or ref in seen:
            continue
        seen.add(ref)
        refs.append(ref)
    return refs


def _extract_owner(text: str) -> str | None:
    patterns = [
        r"\bauthored by\s+([A-Z][A-Za-z .'-]+)",
        r"\bowner(?: is|:)?\s+([A-Z][A-Za-z .'-]+)",
        r"\bby\s+([A-Z][A-Za-z .'-]+)\.?$",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE | re.MULTILINE)
        if match:
            return _clean_phrase(match.group(1))
    return None


def _extract_customer_list(text: str) -> list[str]:
    match = re.search(
        r"\b(?:including|affected customers?:)\s+([A-Z][A-Za-z0-9 .,&'-]+?)(?:\s+had|\s+were|\.|$)",
        text,
        flags=re.IGNORECASE,
    )
    if not match:
        return []

    names = re.split(r",|\band\b", match.group(1))
    return [_clean_phrase(name) for name in names if _clean_phrase(name)]


def _extract_fix(text: str, pr_ref: str | None) -> str:
    if not text.strip():
        return "No prior fix found in graph recall."

    sentences = _sentences(text)
    if pr_ref:
        for sentence in sentences:
            if pr_ref.lower() in sentence.lower():
                return sentence
        return f"{pr_ref} from graph recall."

    for sentence in sentences:
        if re.search(r"\b(resolved|fixed|fix|mitigated|remediated)\b", sentence, re.IGNORECASE):
            return sentence

    return "No prior fix found in graph recall."


def _extract_probable_cause(text: str) -> str:
    for sentence in _sentences(text):
        if re.search(
            r"\b(root cause|due to|caused by|timeout|race|migration)\b", sentence, re.IGNORECASE
        ):
            return sentence
    return "No prior cause found in graph recall."


def _explain_relation(ticket: dict[str, Any], recall: str, matched_incident_id: str | None) -> str:
    component = ticket["component"]
    sentry = ticket.get("sentry_error") or {}
    error_class = sentry.get("error_class")
    signals = [component]
    if error_class:
        signals.append(error_class)

    if matched_incident_id:
        return (
            f"{matched_incident_id} is the best graph match because recall connects the incoming "
            f"ticket to prior context through {', '.join(signals)}."
        )

    if recall.strip():
        return f"Recall returned context, but no single prior incident id was identified for {component}."

    return "Recall returned little usable prior context for this ticket."


def _confidence(
    matched_incident_id: str | None,
    pr_ref: str | None,
    recall: str,
) -> Literal["high", "medium", "low"]:
    if matched_incident_id and pr_ref:
        return "high"
    if matched_incident_id or pr_ref or recall.strip():
        return "medium"
    return "low"


def _sentences(text: str) -> list[str]:
    return [
        _clean_phrase(sentence) for sentence in re.split(r"(?<=[.!?])\s+", text) if sentence.strip()
    ]


def _clean_phrase(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip(" .,\n\t\"'"))
