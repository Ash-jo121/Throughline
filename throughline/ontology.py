from __future__ import annotations

from typing import List

from pydantic import Field

try:
    from cognee.modules.data.models import DataPoint
except ImportError:  # pragma: no cover - supports older Cognee package layouts.
    from cognee.low_level import DataPoint


class Engineer(DataPoint):
    name: str = Field(description="Canonical engineer name.")


class Component(DataPoint):
    name: str = Field(description="Canonical service or product component name.")


class Customer(DataPoint):
    name: str = Field(description="Canonical customer account name.")
    tier: str = Field(default="unknown", description="Customer tier when known.")


class PullRequest(DataPoint):
    pr_id: str = Field(description="Pull request identifier, for example PR #1290.")
    title: str = Field(description="Pull request title.")
    author: Engineer = Field(description="Engineer who authored the pull request.")


class Incident(DataPoint):
    incident_id: str = Field(description="Incident identifier, for example INC-2024-11.")
    date: str = Field(description="Incident date or month.")
    summary: str = Field(description="Incident summary, impact, root cause, and resolution.")
    component: Component = Field(description="Component where the incident occurred.")
    affected_customers: List[Customer] = Field(
        default_factory=list,
        description="Customers affected by the incident.",
    )
    resolved_by: PullRequest = Field(description="Pull request that resolved the incident.")


class SentryError(DataPoint):
    error_class: str = Field(description="Sentry error class.")
    component: Component = Field(description="Component where the error occurs.")
    service: str = Field(description="Service emitting the error.")


class Ticket(DataPoint):
    ticket_id: str = Field(description="Ticket identifier, for example JIRA-4821.")
    summary: str = Field(description="Ticket summary.")
    customer: Customer = Field(description="Customer who raised the ticket.")
    component: Component = Field(description="Component implicated in the ticket.")
    manifests_as: SentryError | None = Field(
        default=None,
        description="Correlated Sentry error for this ticket.",
    )


class ThroughlineGraph(DataPoint):
    """Cognee extraction schema for one support-memory record."""

    incident: Incident | None = Field(
        default=None,
        description="Past incident and its resolution.",
    )
    ticket: Ticket | None = Field(
        default=None,
        description="Incoming or historical customer ticket.",
    )
    sentry_error: SentryError | None = Field(
        default=None,
        description="Observed Sentry error signal.",
    )
