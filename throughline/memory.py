from __future__ import annotations

import inspect
import os
from dataclasses import dataclass
from collections.abc import Iterable
from typing import Any
from uuid import UUID

from throughline.config import DATASET_NAME, configure_environment

configure_environment()

import cognee  # noqa: E402
from cognee.exceptions.exceptions import CogneeValidationError  # noqa: E402
from cognee import SearchType  # noqa: E402
from cognee.memory import FeedbackEntry  # noqa: E402
from throughline.ontology import ThroughlineGraph  # noqa: E402
from throughline.tickets import normalize_ticket  # noqa: E402


EXTRACTION_PROMPT = """Extract a Throughline customer-escalation memory graph.

Preserve exact identifiers, PR numbers, customer names, component names, engineer names, and error
classes. Create stable Component nodes by canonical component name. Connect records with these
relationships:

- Customer RAISED Ticket.
- Ticket MANIFESTS_AS SentryError.
- SentryError OCCURS_IN Component.
- Incident OCCURS_IN Component.
- Incident RESOLVED_BY PullRequest.
- PullRequest AUTHORED_BY Engineer.

Canonicalization rule: if two records mention the exact same component name, they refer to the
same Component node. In particular, every mention of "PaymentService" must resolve to one shared
Component named PaymentService, not separate duplicate PaymentService components.

If a record names a past incident and a resolving PR, make the Incident, Component, PullRequest,
Engineer, and affected Customer entities explicit. The shared Component node is the most important
join key for future recall.
"""


RECALL_PROMPT = """You are Throughline, a customer-escalation memory agent.

Answer by traversing the incident knowledge graph. Return a prior incident or ticket only when it
shares the same Component node as the incoming escalation, or the same exact SentryError entity.
Do not match on generic words such as timeout, error, failure, retry, or backoff when the component
or exact error entity differs. Return the related incident or ticket reference, component, why it is
related, and the pull request or fix that resolved it. If no graph-safe match exists, say no prior
matching incident or ticket was found.
"""


@dataclass(frozen=True)
class RecallResult:
    text: str
    session_id: str | None = None
    qa_id: str | None = None

    def __str__(self) -> str:
        return self.text

    def lower(self) -> str:
        return self.text.lower()


def serialize_incident(record: dict[str, Any]) -> str:
    """Turn a seed/support record into extraction-friendly text."""

    customers = ", ".join(record.get("affected_customers", [])) or "unknown"
    pr = record["resolved_by"]

    lines = [
        "Throughline past incident memory.",
        f"Incident {record['id']} occurred on {record['date']}.",
        f"Incident {record['id']} OCCURS_IN Component {record['component']}.",
        f"Affected Customers: {customers}.",
        f"Summary: {record['summary']}",
        (f'Incident {record["id"]} RESOLVED_BY PullRequest {pr["id"]} titled "{pr["title"]}".'),
        f"PullRequest {pr['id']} AUTHORED_BY Engineer {pr['author']}.",
        (
            f"Resolution memory: for Component {record['component']}, the known fix was "
            f"{pr['id']} - {pr['title']} by {pr['author']}."
        ),
    ]

    if sentry := record.get("sentry_error"):
        lines.append(
            f"SentryError {sentry['error_class']} OCCURS_IN Component {record['component']} "
            f"and service {sentry['service']}."
        )

    return "\n".join(lines)


def serialize_ticket(record: dict[str, Any]) -> str:
    """Turn an incoming ticket signal into extraction-friendly text."""

    customer = record["customer"]
    sentry = record.get("sentry_error")
    lines = [
        "Throughline incoming customer ticket signal.",
        f"Ticket {record['id']} was created on {record['date']}.",
        f"Customer {customer['name']} with tier {customer['tier']} RAISED Ticket {record['id']}.",
        f"Ticket {record['id']} summary: {record['summary']}",
        f"Ticket {record['id']} OCCURS_IN Component {record['component']}.",
        (
            f"Canonical component join key: Component {record['component']} is the same "
            f"Component node used by past incidents in {record['component']}."
        ),
    ]

    if sentry:
        lines.extend(
            [
                (f"Ticket {record['id']} MANIFESTS_AS SentryError {sentry['error_class']}."),
                (
                    f"SentryError {sentry['error_class']} OCCURS_IN Component "
                    f"{record['component']} and service {sentry['service']}."
                ),
            ]
        )

    return "\n".join(lines)


def require_llm_key() -> None:
    if not os.getenv("LLM_API_KEY"):
        raise RuntimeError(
            "LLM_API_KEY is required for Cognee remember/recall. "
            "Copy .env.example to .env and set LLM_API_KEY before running Day 1 commands."
        )


async def remember_incident(record: dict[str, Any]) -> list[str]:
    """Write one incident/ticket record to the Cognee graph."""

    require_llm_key()
    before_data_ids = await _current_dataset_data_ids()
    result = await cognee.remember(
        serialize_incident(record),
        dataset_name=DATASET_NAME,
        graph_model=ThroughlineGraph,
        custom_prompt=EXTRACTION_PROMPT,
        node_set=["throughline", "incidents", record["component"]],
        self_improvement=True,
    )
    return await _new_data_ids(before_data_ids, result)


async def remember_ticket(record: dict[str, Any]) -> list[str]:
    """Write one incoming ticket signal to the Cognee graph."""

    require_llm_key()
    normalized = normalize_ticket(record)
    before_data_ids = await _current_dataset_data_ids()
    result = await cognee.remember(
        serialize_ticket(normalized),
        dataset_name=DATASET_NAME,
        graph_model=ThroughlineGraph,
        custom_prompt=EXTRACTION_PROMPT,
        node_set=["throughline", "tickets", normalized["component"]],
        self_improvement=True,
    )
    return await _new_data_ids(before_data_ids, result)


async def recall_related(
    query: str,
    *,
    session_id: str | None = None,
    feedback_influence: float = 0.5,
) -> RecallResult:
    """Query Cognee graph memory for related incidents and fixes."""

    require_llm_key()
    try:
        results = await cognee.recall(
            query_text=query,
            query_type=SearchType.GRAPH_COMPLETION,
            datasets=[DATASET_NAME],
            top_k=8,
            auto_route=False,
            system_prompt=RECALL_PROMPT,
            include_references=True,
            session_id=session_id,
            feedback_influence=feedback_influence,
        )
    except CogneeValidationError as error:
        if "RecallPreconditionError" not in str(error):
            raise
        return RecallResult(
            text=(
                "No prior Throughline memory is available yet. "
                "Generate this brief, then remember the Jira ticket for future recall."
            ),
            session_id=session_id,
            qa_id=None,
        )
    text = "\n\n".join(_result_text(result) for result in _flatten(results) if _result_text(result))
    qa_id = await _latest_qa_id(session_id) if session_id else None
    return RecallResult(text=text, session_id=session_id, qa_id=qa_id)


async def improve_from_feedback(
    *,
    session_id: str | None,
    qa_id: str | None,
    verdict: str,
    note: str | None = None,
) -> dict[str, Any]:
    """Attach user feedback to a recall session and run Cognee improve()."""

    require_llm_key()
    score = 1 if verdict == "up" else -1
    result: dict[str, Any] = {"feedback_score": score}

    if session_id and qa_id:
        feedback = FeedbackEntry(qa_id=qa_id, feedback_text=note, feedback_score=score)
        remember_result = await cognee.remember(
            feedback,
            dataset_name=DATASET_NAME,
            session_id=session_id,
        )
        if not remember_result:
            raise RuntimeError(remember_result.error or "Cognee feedback remember failed")
        result["feedback_entry_id"] = getattr(remember_result, "entry_id", qa_id)
        result["session_id"] = session_id
        await cognee.improve(dataset=DATASET_NAME, session_ids=[session_id])
        result["improve_scope"] = "session"
    else:
        await cognee.improve(dataset=DATASET_NAME)
        result["improve_scope"] = "dataset"

    return result


async def forget_customer_data(data_ids: Iterable[str]) -> list[dict[str, Any]]:
    """Forget specific customer-owned records while leaving shared incident memory intact."""

    require_llm_key()
    results = []
    for data_id in data_ids:
        results.append(await cognee.forget(dataset=DATASET_NAME, data_id=UUID(str(data_id))))
    return results


async def reset_memory() -> None:
    """Clear local Cognee state for repeatable demos/tests."""

    prune = getattr(cognee, "prune", None)
    if prune is not None:
        prune_data = getattr(prune, "prune_data", None)
        prune_system = getattr(prune, "prune_system", None)
        if prune_data is not None:
            await prune_data()
        if prune_system is not None:
            await prune_system(metadata=True)
        return

    forget = getattr(cognee, "forget", None)
    if forget is not None:
        parameters = inspect.signature(forget).parameters
        if "everything" in parameters:
            await forget(everything=True)
        else:
            await forget(dataset=DATASET_NAME)


def _flatten(results: Any) -> Iterable[Any]:
    if isinstance(results, list):
        for item in results:
            if isinstance(item, list):
                yield from item
            else:
                yield item
        return

    yield results


def _result_text(result: Any) -> str:
    if result is None:
        return ""

    if isinstance(result, str):
        return result

    text = getattr(result, "text", None)
    if text:
        return str(text)

    content = getattr(result, "content", None)
    if content:
        return str(content)

    if isinstance(result, dict):
        for key in ("text", "text_result", "answer", "content"):
            if result.get(key):
                return str(result[key])
        if result.get("search_result"):
            return str(result["search_result"])

    return str(result)


def _data_ids(result: Any) -> list[str]:
    items = getattr(result, "items", []) or []
    return [str(item["id"]) for item in items if isinstance(item, dict) and item.get("id")]


async def _new_data_ids(before_data_ids: set[str], result: Any) -> list[str]:
    after_data_ids = await _current_dataset_data_ids()
    new_data_ids = sorted(after_data_ids - before_data_ids)
    if new_data_ids:
        return new_data_ids

    return _data_ids(result)


async def _current_dataset_data_ids() -> set[str]:
    datasets_api = getattr(cognee, "datasets", None)
    list_datasets = getattr(datasets_api, "list_datasets", None)
    list_data = getattr(datasets_api, "list_data", None)
    if list_datasets is None or list_data is None:
        return set()

    try:
        dataset_id = await _dataset_id()
        if dataset_id is None:
            return set()

        rows = await list_data(dataset_id)
    except Exception:
        return set()

    return {_entity_id(row) for row in rows if _entity_id(row)}


async def _dataset_id() -> Any | None:
    datasets = await cognee.datasets.list_datasets()
    for dataset in datasets:
        name = _entity_value(dataset, "name") or _entity_value(dataset, "dataset_name")
        if name == DATASET_NAME:
            return _entity_value(dataset, "id")
    return None


def _entity_id(value: Any) -> str | None:
    entity_id = _entity_value(value, "id")
    return str(entity_id) if entity_id else None


def _entity_value(value: Any, key: str) -> Any:
    if isinstance(value, dict):
        return value.get(key)
    return getattr(value, key, None)


async def _latest_qa_id(session_id: str | None) -> str | None:
    if not session_id:
        return None

    session_api = getattr(cognee, "session", None)
    get_session = getattr(session_api, "get_session", None)
    if get_session is None:
        return None

    entries = await get_session(session_id=session_id)
    if not entries:
        return None

    return str(getattr(entries[-1], "qa_id", "") or "") or None
