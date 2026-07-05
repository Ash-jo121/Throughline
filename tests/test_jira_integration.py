from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient

from api.app import app
from throughline.jira import JiraConfigError, JiraIssueNotFound, jira_issue_to_ticket
from throughline.store import persist_brief
from throughline.synthesize import IncidentBrief


def test_jira_issue_to_ticket_extracts_demo_labels() -> None:
    issue = {
        "key": "ESC-1",
        "fields": {
            "summary": "Payments failing intermittently at checkout.",
            "created": "2026-07-05T09:00:00.000+0000",
            "labels": ["customer:Acme-Corp", "component:PaymentService", "sentry:StripeTimeout"],
            "reporter": {"displayName": "Sales Team"},
        },
    }

    ticket = jira_issue_to_ticket(issue)

    assert ticket["id"] == "ESC-1"
    assert ticket["raw_customer"] == "Acme Corp"
    assert ticket["component"] == "PaymentService"
    assert ticket["sentry_error"]["error_class"] == "StripeTimeout"


def test_pull_by_key_import_returns_brief_link(monkeypatch) -> None:
    calls = []

    async def fake_build(ticket):
        calls.append(("build", ticket["id"]))
        return _brief(ticket["id"])

    async def fake_remember(ticket):
        calls.append(("remember", ticket["id"]))

    monkeypatch.setenv("THROUGHLINE_PUBLIC_BASE_URL", "https://throughline.example")
    monkeypatch.setattr(
        "api.app.fetch_jira_issue", lambda issue_key: {"key": issue_key, "fields": {}}
    )
    monkeypatch.setattr(
        "api.app.jira_issue_to_ticket",
        lambda issue: {
            "id": issue["key"],
            "raw_customer": "Acme Corp",
            "component": "PaymentService",
            "summary": "Payments failing intermittently at checkout.",
            "date": "2026-07-05",
        },
    )
    monkeypatch.setattr("api.app.build_incident_brief", fake_build)
    monkeypatch.setattr("api.app.remember_ticket_background", fake_remember)

    response = TestClient(app).post("/integrations/jira/issues/ESC-1/brief")

    assert response.status_code == 200
    payload = response.json()
    assert payload["brief_id"]
    assert payload["brief_path"] == f"/brief/{payload['brief_id']}"
    assert payload["brief_url"] == f"https://throughline.example/brief/{payload['brief_id']}"
    assert calls == [("build", "ESC-1"), ("remember", "ESC-1")]


def test_pull_by_key_import_reports_missing_config(monkeypatch) -> None:
    def fake_fetch(_issue_key: str):
        raise JiraConfigError("Missing Jira configuration: JIRA_SITE_URL")

    monkeypatch.setattr("api.app.fetch_jira_issue", fake_fetch)
    monkeypatch.setattr("api.app.jira_missing_env_vars", lambda: ["JIRA_SITE_URL"])

    response = TestClient(app).post("/integrations/jira/issues/ESC-404/brief")

    assert response.status_code == 400
    assert "JIRA_SITE_URL" in response.json()["detail"]


def test_pull_by_key_import_reports_unknown_issue(monkeypatch) -> None:
    def fake_fetch(_issue_key: str):
        raise JiraIssueNotFound("Jira issue ESC-404 was not found.")

    monkeypatch.setattr("api.app.fetch_jira_issue", fake_fetch)

    response = TestClient(app).post("/integrations/jira/issues/ESC-404/brief")

    assert response.status_code == 404
    assert "ESC-404" in response.json()["detail"]


def test_webhook_ignores_non_create_events(monkeypatch) -> None:
    calls = []
    monkeypatch.delenv("JIRA_WEBHOOK_SECRET", raising=False)
    monkeypatch.setattr(
        "api.app._generate_jira_brief_background", lambda issue_key: calls.append(issue_key)
    )

    response = TestClient(app).post(
        "/integrations/jira/webhook",
        json={"webhookEvent": "jira:issue_updated", "issue": {"key": "ESC-1"}},
    )

    assert response.status_code == 200
    assert response.json() == {"status": "ignored", "issue_key": None}
    assert calls == []


def test_webhook_accepts_create_event_and_schedules_background(monkeypatch) -> None:
    calls = []

    async def fake_generate(issue_key: str):
        calls.append(issue_key)

    monkeypatch.delenv("JIRA_WEBHOOK_SECRET", raising=False)
    monkeypatch.setenv("JIRA_SITE_URL", "https://example.atlassian.net")
    monkeypatch.setenv("JIRA_EMAIL", "demo@example.com")
    monkeypatch.setenv("JIRA_API_TOKEN", "token")
    monkeypatch.setattr("api.app._generate_jira_brief_background", fake_generate)

    response = TestClient(app).post(
        "/integrations/jira/webhook",
        json={"webhookEvent": "jira:issue_created", "issue": {"key": "ESC-1"}},
    )

    assert response.status_code == 200
    assert response.json() == {"status": "accepted", "issue_key": "ESC-1"}
    assert calls == ["ESC-1"]


def test_webhook_rejects_bad_secret(monkeypatch) -> None:
    monkeypatch.setenv("JIRA_WEBHOOK_SECRET", "correct")

    response = TestClient(app).post(
        "/integrations/jira/webhook?secret=wrong",
        json={"webhookEvent": "jira:issue_created", "issue": {"key": "ESC-1"}},
    )

    assert response.status_code == 401


def test_latest_brief_returns_most_recent(monkeypatch) -> None:
    db_path = Path(".throughline") / f"test_latest_{uuid4()}.db"
    monkeypatch.setattr("throughline.store.BRIEF_DB_PATH", db_path)
    older = _brief("ESC-1")
    newer = _brief("ESC-2")

    persist_brief(older)
    persist_brief(newer)

    response = TestClient(app).get("/briefs/latest")

    assert response.status_code == 200
    assert response.json()["incident_ref"] == "ESC-2"


def test_list_briefs_returns_newest_first(monkeypatch) -> None:
    db_path = Path(".throughline") / f"test_list_{uuid4()}.db"
    monkeypatch.setattr("throughline.store.BRIEF_DB_PATH", db_path)
    older = _brief("ESC-1")
    newer = _brief("ESC-2")

    persist_brief(older)
    persist_brief(newer)

    response = TestClient(app).get("/briefs")

    assert response.status_code == 200
    assert [item["incident_ref"] for item in response.json()] == ["ESC-2", "ESC-1"]


def test_persisting_same_incident_ref_replaces_dashboard_row(monkeypatch) -> None:
    db_path = Path(".throughline") / f"test_upsert_{uuid4()}.db"
    monkeypatch.setattr("throughline.store.BRIEF_DB_PATH", db_path)
    older = _brief("ESC-1")
    newer = _brief("ESC-1")
    newer.title = "Updated brief"

    persist_brief(older)
    persist_brief(newer)

    response = TestClient(app).get("/briefs")

    assert response.status_code == 200
    payload = response.json()
    assert len(payload) == 1
    assert payload[0]["title"] == "Updated brief"


def _brief(issue_key: str) -> IncidentBrief:
    return IncidentBrief(
        incident_ref=issue_key,
        customer="Acme Corp",
        component="PaymentService",
        title=f"PaymentService escalation for {issue_key}",
        probable_cause="Stripe webhook timeout behavior.",
        matched_incident_id="INC-2024-11",
        why_related="Shared PaymentService and StripeTimeout signals.",
        recommended_fix="PR #1290 - Add exponential backoff.",
        suggested_owner="Priya",
        confidence="high",
        related=["INC-2024-11"],
    )
