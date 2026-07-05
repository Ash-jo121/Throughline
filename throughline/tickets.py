from __future__ import annotations

from copy import deepcopy
from typing import Any

from throughline.resolve import resolve_customer


def normalize_ticket(ticket: dict[str, Any]) -> dict[str, Any]:
    """Return a ticket with canonical customer fields for recall, synthesis, and memory."""

    normalized = deepcopy(ticket)
    # Day 2 fixtures/API payloads carry raw_customer so the resolver step is explicit.
    # Day 1 memory probes may already carry a normalized customer object.
    raw_customer = normalized.get("raw_customer")
    existing_customer = normalized.get("customer")

    if isinstance(existing_customer, dict):
        customer_name = existing_customer.get("name", "")
        customer_tier = existing_customer.get("tier", "unknown")
    else:
        customer_name = str(raw_customer or existing_customer or "").strip()
        customer_tier = normalized.get("customer_tier", "unknown")

    canonical = resolve_customer(customer_name)
    normalized["raw_customer"] = raw_customer or customer_name
    normalized["customer"] = {"name": canonical, "tier": customer_tier or "unknown"}
    normalized.setdefault("date", "")

    return normalized


def ticket_recall_query(ticket: dict[str, Any]) -> str:
    """Build the graph-recall query for an incoming ticket."""

    normalized = normalize_ticket(ticket)
    sentry = normalized.get("sentry_error") or {}
    error_class = sentry.get("error_class")
    sentry_clause = f" Correlated Sentry error: {error_class}." if error_class else ""

    return (
        f"{normalized['customer']['name']} reports {normalized['summary']} "
        f"in {normalized['component']}.{sentry_clause} "
        "Have we seen this before in the same component or with the same exact error entity? "
        "Return either a past incident with a known fix, or earlier tickets reporting the same "
        "issue even if no fix is known yet. If a fix exists, what was it?"
    )
