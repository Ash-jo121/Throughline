from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from throughline.memory import forget_customer_data, improve_from_feedback
from throughline.synthesize import IncidentBrief
from throughline.store import (
    delete_customer_briefs,
    get_all_briefs,
    list_customer_data_ids,
    mark_customer_data_forgotten,
    persist_brief,
    persist_customer_data,
)


class _RememberResult:
    status = "session_stored"
    error = None
    entry_id = "qa-1"

    def __bool__(self) -> bool:
        return True


@pytest.mark.asyncio
async def test_improve_from_feedback_stores_feedback_and_runs_session_improve(monkeypatch) -> None:
    calls = []

    async def fake_remember(entry, *, dataset_name: str, session_id: str):
        calls.append(("remember", dataset_name, session_id, entry.qa_id, entry.feedback_score))
        return _RememberResult()

    async def fake_improve(*, dataset: str, session_ids: list[str] | None = None):
        calls.append(("improve", dataset, session_ids))

    monkeypatch.setenv("LLM_API_KEY", "test-key")
    monkeypatch.setattr(
        "throughline.memory.cognee",
        SimpleNamespace(remember=fake_remember, improve=fake_improve),
    )

    result = await improve_from_feedback(
        session_id="sess-1",
        qa_id="qa-1",
        verdict="up",
        note="correct fix",
    )

    assert result["improve_scope"] == "session"
    assert calls == [
        ("remember", "throughline_day1", "sess-1", "qa-1", 1),
        ("improve", "throughline_day1", ["sess-1"]),
    ]


@pytest.mark.asyncio
async def test_improve_from_feedback_falls_back_to_dataset_improve(monkeypatch) -> None:
    calls = []

    async def fake_improve(*, dataset: str, session_ids: list[str] | None = None):
        calls.append(("improve", dataset, session_ids))

    monkeypatch.setenv("LLM_API_KEY", "test-key")
    monkeypatch.setattr("throughline.memory.cognee", SimpleNamespace(improve=fake_improve))

    result = await improve_from_feedback(
        session_id=None,
        qa_id=None,
        verdict="down",
        note=None,
    )

    assert result["improve_scope"] == "dataset"
    assert calls == [("improve", "throughline_day1", None)]


@pytest.mark.asyncio
async def test_forget_customer_data_calls_cognee_for_each_data_id(monkeypatch) -> None:
    data_id = str(uuid4())
    calls = []

    async def fake_forget(*, dataset: str, data_id):
        calls.append((dataset, str(data_id)))
        return {"status": "success", "data_id": str(data_id)}

    monkeypatch.setenv("LLM_API_KEY", "test-key")
    monkeypatch.setattr("throughline.memory.cognee", SimpleNamespace(forget=fake_forget))

    result = await forget_customer_data([data_id])

    assert result == [{"status": "success", "data_id": data_id}]
    assert calls == [("throughline_day1", data_id)]


def test_customer_data_is_not_returned_after_marking_forgotten(monkeypatch) -> None:
    db_path = Path(".throughline") / f"test_customer_data_{uuid4()}.db"
    monkeypatch.setattr("throughline.store.BRIEF_DB_PATH", db_path)
    data_id = str(uuid4())

    persist_customer_data("Acme Corp", data_id, "JIRA-4821")
    assert list_customer_data_ids("Acme Corp") == [data_id]

    mark_customer_data_forgotten("Acme Corp", [data_id])

    assert list_customer_data_ids("Acme Corp") == []


def test_delete_customer_briefs_preserves_other_primary_customers(monkeypatch) -> None:
    db_path = Path(".throughline") / f"test_customer_briefs_{uuid4()}.db"
    monkeypatch.setattr("throughline.store.BRIEF_DB_PATH", db_path)
    acme = _brief("JIRA-1", "Acme Corp", also_affected=["Globex", "Initech"])
    globex = _brief("JIRA-2", "Globex")

    persist_brief(acme)
    persist_brief(globex)

    deleted = delete_customer_briefs("Globex")
    remaining = get_all_briefs()

    assert deleted == 1
    assert [brief.customer for brief in remaining] == ["Acme Corp"]
    assert remaining[0].also_affected == ["Initech"]


def _brief(
    incident_ref: str,
    customer: str,
    *,
    also_affected: list[str] | None = None,
) -> IncidentBrief:
    return IncidentBrief(
        incident_ref=incident_ref,
        customer=customer,
        component="PaymentService",
        title=f"PaymentService escalation for {customer}",
        probable_cause="Stripe webhook timeout behavior.",
        matched_incident_id="INC-2024-11",
        why_related="Shared PaymentService and StripeTimeout signals.",
        recommended_fix="PR #1290 - Add exponential backoff.",
        suggested_owner="Priya",
        also_affected=also_affected or [],
        confidence="high",
        related=["INC-2024-11"],
    )
