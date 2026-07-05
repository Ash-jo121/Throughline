from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from throughline.config import BRIEF_DB_PATH, DATASET_NAME
from throughline.memory import (
    SearchType,
    _flatten,
    _result_text,
    cognee,
    forget_customer_data,
    improve_from_feedback,
    recall_related,
    remember_incident,
    remember_ticket,
    reset_memory,
)
from throughline.seed import HERO_QUERY, INCOMING_TICKET, PAST_INCIDENTS
from throughline.service import build_incident_brief
from throughline.store import (
    list_customer_data_ids,
    mark_customer_data_forgotten,
    persist_customer_data,
)
from throughline.tickets import normalize_ticket


TICKET_QUERY = (
    "List customer-owned ticket signals for Acme Corp in PaymentService. "
    "Return ticket IDs and summaries only. Do not list past incidents."
)

TICKET_RECALL_PROMPT = """You are verifying customer-owned ticket memory.

Return only customer ticket signals from the graph. Include ticket IDs and summaries when present.
If no customer-owned ticket is present, say that no customer ticket was found. Do not substitute
past incidents or pull requests.
"""


async def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    try:
        await _run_demo()
    finally:
        await _close_cognee_telemetry_session()


async def _run_demo() -> None:
    _reset_local_store()
    await reset_memory()
    print("\n== Backfill shared incident memory ==")
    for incident in PAST_INCIDENTS:
        data_ids = await remember_incident(incident)
        print(f"{incident['id']} data_ids={data_ids}")

    print("\n== R1 improve demo: same recall before and after feedback ==")
    feedback_session_id = f"demo_feedback_{uuid4()}"
    before_improve = await recall_related(HERO_QUERY, session_id=feedback_session_id)
    print(f"session_id={before_improve.session_id}")
    print(f"qa_id={before_improve.qa_id}")
    print("\nBefore feedback/improve:")
    print(before_improve.text)

    if not before_improve.qa_id:
        raise SystemExit("qa_id was not captured from Cognee session runtime.")

    improve_result = await improve_from_feedback(
        session_id=before_improve.session_id,
        qa_id=before_improve.qa_id,
        verdict="up",
        note="Correct match: PaymentService Stripe timeout was fixed by PR #1290.",
    )
    print(f"\nimprove_result={improve_result}")

    after_improve = await recall_related(
        HERO_QUERY,
        session_id=f"demo_feedback_after_{uuid4()}",
        feedback_influence=0.8,
    )
    print("\nAfter feedback/improve, same recall:")
    print(after_improve.text)

    print("\n== R2 forget demo: remember customer ticket, then forget by data_id ==")
    brief = await build_incident_brief(INCOMING_TICKET)
    print(f"created_brief_id={brief.brief_id}")
    print(
        "API demo beat: after POST /incidents, pause briefly for BackgroundTasks to remember ticket."
    )
    await asyncio.sleep(2)

    normalized = normalize_ticket(INCOMING_TICKET)
    ticket_data_ids = await remember_ticket(normalized)
    print(f"runtime ticket data_ids={ticket_data_ids}")
    if not ticket_data_ids:
        raise SystemExit("_data_ids did not extract any Cognee data_id from remember_ticket().")

    for data_id in ticket_data_ids:
        persist_customer_data(
            normalized["customer"]["name"],
            data_id,
            source_ref=normalized["id"],
        )

    stored_data_ids = list_customer_data_ids(normalized["customer"]["name"])
    print(f"stored customer_data ids={stored_data_ids}")

    before_forget = await _recall_customer_ticket()
    print("\nBefore forget, same customer-ticket recall:")
    print(before_forget)
    if normalized["id"].lower() not in before_forget.lower():
        raise SystemExit("Before-forget recall did not surface the incoming customer ticket.")

    forget_results = await forget_customer_data(stored_data_ids)
    mark_customer_data_forgotten(normalized["customer"]["name"], stored_data_ids)
    print(f"\nforget_results={forget_results}")

    after_forget = await _recall_customer_ticket()
    print("\nAfter forget, same customer-ticket recall:")
    print(after_forget)
    if normalized["id"].lower() in after_forget.lower():
        raise SystemExit("After-forget recall still surfaced the deleted customer ticket.")

    shared_after_forget = await recall_related(HERO_QUERY, session_id=f"demo_shared_{uuid4()}")
    print("\nShared incident knowledge still works after customer forget:")
    print(shared_after_forget.text)

    print("\nLifecycle demo passed: qa_id, data_id, improve, and forget verified at runtime.")


async def _recall_customer_ticket() -> str:
    results = await cognee.recall(
        query_text=TICKET_QUERY,
        query_type=SearchType.GRAPH_COMPLETION,
        datasets=[DATASET_NAME],
        top_k=8,
        auto_route=False,
        system_prompt=TICKET_RECALL_PROMPT,
        include_references=True,
        only_context=True,
    )
    text = "\n\n".join(_result_text(result) for result in _flatten(results) if _result_text(result))
    return text or "No customer ticket context found."


def _reset_local_store() -> None:
    BRIEF_DB_PATH.unlink(missing_ok=True)


async def _close_cognee_telemetry_session() -> None:
    try:
        from cognee.shared import utils

        session = getattr(utils, "_telemetry_session", None)
        if session is not None and not session.closed:
            await session.close()
            utils._telemetry_session = None
    except Exception:
        pass


if __name__ == "__main__":
    asyncio.run(main())
