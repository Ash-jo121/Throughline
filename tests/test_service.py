from __future__ import annotations

from types import SimpleNamespace

from throughline.seed import INCOMING_TICKET
from throughline.service import build_incident_brief
from throughline.store import get_brief


async def test_build_incident_brief_recalls_before_persisting(monkeypatch) -> None:
    monkeypatch.setenv("LLM_API_KEY", "")
    calls = []

    async def fake_recall(query: str, **kwargs) -> SimpleNamespace:
        calls.append(("recall", query, kwargs))
        return SimpleNamespace(
            text="INC-2024-11 resolved by PR #1290 backoff, owner Priya.",
            session_id=kwargs["session_id"],
            qa_id="qa-1",
        )

    monkeypatch.setattr("throughline.service.recall_related", fake_recall)

    brief = await build_incident_brief(INCOMING_TICKET)

    assert calls and calls[0][0] == "recall"
    assert brief.customer == "Acme Corp"
    assert get_brief(brief.brief_id) == brief
