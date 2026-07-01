from __future__ import annotations

PAST_INCIDENTS = [
    {
        "id": "INC-2024-11",
        "date": "2024-11",
        "component": "PaymentService",
        "summary": (
            "Several enterprise customers reported orders stuck in a pending state during "
            "checkout. Root cause: Stripe webhook timeouts in the billing pipeline. Resolved by "
            "adding exponential backoff to webhook retries."
        ),
        "affected_customers": ["Acme Corp", "Globex", "Initech"],
        "resolved_by": {
            "id": "PR #1290",
            "title": "Add exponential backoff to Stripe webhook retries",
            "author": "Priya",
        },
        "sentry_error": {
            "error_class": "StripeWebhookTimeout",
            "service": "billing-worker",
        },
    },
    {
        "id": "INC-2025-03",
        "date": "2025-03",
        "component": "SearchService",
        "summary": (
            "Product search requests were failing with elevated latency and intermittent 500 "
            "errors after an index migration."
        ),
        "affected_customers": ["Umbrella Inc"],
        "resolved_by": {
            "id": "PR #1544",
            "title": "Rebuild search index shards",
            "author": "Dan",
        },
        "sentry_error": {
            "error_class": "SearchIndexUnavailable",
            "service": "catalog-search",
        },
    },
    {
        "id": "INC-2025-07",
        "date": "2025-07",
        "component": "AuthService",
        "summary": "Users intermittently logged out due to token refresh race condition.",
        "affected_customers": ["Globex"],
        "resolved_by": {
            "id": "PR #1602",
            "title": "Fix token refresh race",
            "author": "Priya",
        },
        "sentry_error": {
            "error_class": "TokenRefreshRace",
            "service": "identity-api",
        },
    },
]

HERO_QUERY = (
    "Acme Corp reports payments failing intermittently at checkout in PaymentService. "
    "Correlated Sentry error: StripeTimeout in PaymentService. Have we seen this before "
    "and what fixed it?"
)
