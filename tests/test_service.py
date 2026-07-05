from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

from throughline.seed import INCOMING_TICKET
from throughline.service import build_incident_brief
from throughline.store import get_brief
from throughline.tickets import ticket_recall_query


async def test_build_incident_brief_recalls_before_persisting(monkeypatch) -> None:
    monkeypatch.setenv("LLM_API_KEY", "")
    monkeypatch.setenv("JIRA_SITE_URL", "https://example.atlassian.net")
    calls = []

    async def fake_recall(query: str, **kwargs) -> SimpleNamespace:
        calls.append(("recall", query, kwargs))
        return SimpleNamespace(
            text=(
                "INC-2024-11 occurred in PaymentService with StripeTimeout and was resolved "
                "by PR #1290 backoff, owner Priya."
            ),
            session_id=kwargs["session_id"],
            qa_id="qa-1",
        )

    monkeypatch.setattr("throughline.service.recall_related", fake_recall)

    brief = await build_incident_brief(INCOMING_TICKET)

    assert calls and calls[0][0] == "recall"
    assert brief.customer == "Acme Corp"
    assert [link.kind for link in brief.source_links] == ["jira", "pull_request", "sentry"]
    assert brief.source_links[0].url == "https://example.atlassian.net/browse/JIRA-4821"
    assert get_brief(brief.brief_id) == brief


async def test_build_incident_brief_clears_unrelated_recall(monkeypatch) -> None:
    monkeypatch.setenv("LLM_API_KEY", "")
    monkeypatch.delenv("JIRA_SITE_URL", raising=False)
    ticket = {
        "id": "JIRA-9001",
        "raw_customer": "Replit",
        "component": "OnboardingCampaignService",
        "summary": "Campaign jobs are timing out.",
        "date": "2026-07-05",
        "sentry_error": {"error_class": "CampaignTimeout", "service": "campaign-worker"},
    }

    async def fake_recall(_query: str, **kwargs) -> SimpleNamespace:
        return SimpleNamespace(
            text="INC-2024-11 occurred in PaymentService and was resolved by PR #1290.",
            session_id=kwargs["session_id"],
            qa_id="qa-1",
        )

    monkeypatch.setattr("throughline.service.recall_related", fake_recall)

    brief = await build_incident_brief(ticket)

    assert brief.matched_incident_id is None
    assert brief.related == []
    assert brief.also_affected == []
    assert brief.confidence == "low"
    assert [link.kind for link in brief.source_links] == ["sentry"]


async def test_build_incident_brief_can_match_prior_jira_ticket(monkeypatch) -> None:
    db_path = Path(".throughline") / f"test_ticket_match_{uuid4()}.db"
    monkeypatch.setattr("throughline.store.BRIEF_DB_PATH", db_path)
    monkeypatch.setenv("LLM_API_KEY", "")
    monkeypatch.delenv("JIRA_SITE_URL", raising=False)
    ticket = {
        "id": "KAN-6",
        "raw_customer": "Replit",
        "component": "CampaignScheduler",
        "summary": "Campaign sends are timing out.",
        "date": "2026-07-05",
        "sentry_error": {"error_class": "CampaignTimeout", "service": "campaign-worker"},
    }

    async def fake_recall(_query: str, **kwargs) -> SimpleNamespace:
        return SimpleNamespace(
            text=(
                "Ticket KAN-5 OCCURS_IN Component CampaignScheduler. "
                "KAN-5 MANIFESTS_AS SentryError CampaignTimeout. "
                "The fix was to drain the stuck campaign queue and restart the scheduler."
            ),
            session_id=kwargs["session_id"],
            qa_id="qa-1",
        )

    monkeypatch.setattr("throughline.service.recall_related", fake_recall)

    brief = await build_incident_brief(ticket)

    assert brief.matched_incident_id == "KAN-5"
    assert brief.related == ["KAN-5"]
    assert "KAN-6" not in brief.related
    assert "earlier Jira ticket" in brief.why_related
    assert "new" not in brief.why_related.lower()
    assert "no confirmed fix is recorded yet" in brief.recommended_fix
    assert brief.confidence == "medium"


def test_ticket_recall_query_includes_open_prior_tickets() -> None:
    query = ticket_recall_query(
        {
            "id": "KAN-8",
            "raw_customer": "Replit",
            "component": "CampaignScheduler",
            "summary": "Campaign sends are timing out.",
            "date": "2026-07-05",
            "sentry_error": {"error_class": "CampaignTimeout"},
        }
    )

    assert "same component" in query
    assert "earlier tickets reporting the same issue" in query
    assert "even if no fix is known yet" in query
