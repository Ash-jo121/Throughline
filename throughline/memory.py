from __future__ import annotations

import inspect
import os
from collections.abc import Iterable
from typing import Any

from throughline.config import DATASET_NAME, configure_environment

configure_environment()

import cognee  # noqa: E402
from cognee import SearchType  # noqa: E402
from throughline.ontology import ThroughlineGraph  # noqa: E402


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

If a record names a past incident and a resolving PR, make the Incident, Component, PullRequest,
Engineer, and affected Customer entities explicit. The shared Component node is the most important
join key for future recall.
"""


RECALL_PROMPT = """You are Throughline, a customer-escalation memory agent.

Answer by traversing the incident knowledge graph. Prefer past incidents that share the same
component, error class, or customer with the incoming escalation. Return the related incident ID,
component, why it is related, and the pull request or fix that resolved it. Do not present an
unrelated incident as the resolution.
"""


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


def require_llm_key() -> None:
    if not os.getenv("LLM_API_KEY"):
        raise RuntimeError(
            "LLM_API_KEY is required for Cognee remember/recall. "
            "Copy .env.example to .env and set LLM_API_KEY before running Day 1 commands."
        )


async def remember_incident(record: dict[str, Any]) -> None:
    """Write one incident/ticket record to the Cognee graph."""

    require_llm_key()
    await cognee.remember(
        serialize_incident(record),
        dataset_name=DATASET_NAME,
        graph_model=ThroughlineGraph,
        custom_prompt=EXTRACTION_PROMPT,
        node_set=["throughline", "incidents", record["component"]],
        self_improvement=False,
    )


async def recall_related(query: str) -> str:
    """Query Cognee graph memory for related incidents and fixes."""

    require_llm_key()
    results = await cognee.recall(
        query_text=query,
        query_type=SearchType.GRAPH_COMPLETION,
        datasets=[DATASET_NAME],
        top_k=8,
        auto_route=False,
        system_prompt=RECALL_PROMPT,
        include_references=True,
    )
    return "\n\n".join(_result_text(result) for result in _flatten(results) if _result_text(result))


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

    if isinstance(result, dict):
        for key in ("text", "text_result", "answer", "content"):
            if result.get(key):
                return str(result[key])
        if result.get("search_result"):
            return str(result["search_result"])

    return str(result)
