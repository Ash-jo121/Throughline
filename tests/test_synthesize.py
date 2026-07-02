from __future__ import annotations

from throughline.resolve import resolve_customer
from throughline.seed import INCOMING_TICKET
from throughline.store import get_brief, persist_brief
from throughline.synthesize import synthesize_brief
from throughline.tickets import normalize_ticket


RECALL_OUTPUT = """
The closest match is INC-2024-11 in PaymentService. Several enterprise customers
including Acme Corp, Globex, and Initech had orders stuck in pending state during
checkout due to Stripe webhook timeouts in the billing pipeline. It was resolved by
PR #1290, "Add exponential backoff to Stripe webhook retries", authored by Priya.
"""


async def test_synthesize_brief_names_paymentservice_backoff_fix() -> None:
    ticket = normalize_ticket(INCOMING_TICKET)
    brief = await synthesize_brief(ticket, RECALL_OUTPUT)
    persist_brief(brief)
    stored = get_brief(brief.brief_id)

    assert resolve_customer(INCOMING_TICKET["raw_customer"]) == "Acme Corp"
    assert brief.customer == "Acme Corp"
    assert brief.component == "PaymentService"
    assert "1290" in brief.recommended_fix.lower() or "backoff" in brief.recommended_fix.lower()
    assert brief.suggested_owner in ("Priya", None)
    assert brief.matched_incident_id == "INC-2024-11"
    assert brief.brief_id
    assert stored == brief
