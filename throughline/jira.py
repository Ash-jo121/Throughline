from __future__ import annotations

import base64
import json
import os
import re
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

from throughline.config import configure_environment


configure_environment()

JIRA_ENV_VARS = ("JIRA_SITE_URL", "JIRA_EMAIL", "JIRA_API_TOKEN")


class JiraConfigurationError(RuntimeError):
    """Raised when Jira REST credentials are not configured."""


class JiraConfigError(JiraConfigurationError):
    """Backward-compatible name for missing Jira configuration."""


class JiraIssueNotFound(RuntimeError):
    """Raised when Jira cannot find the requested issue key."""


class JiraRequestError(RuntimeError):
    """Raised when Jira REST returns an unexpected error."""


@dataclass(frozen=True)
class JiraConfig:
    site_url: str
    email: str
    api_token: str


def jira_configured() -> bool:
    return all(os.getenv(key) for key in JIRA_ENV_VARS)


def jira_missing_env_vars() -> list[str]:
    return [key for key in JIRA_ENV_VARS if not os.getenv(key)]


def load_jira_config() -> JiraConfig:
    site_url = os.getenv("JIRA_SITE_URL", "").strip().rstrip("/")
    email = os.getenv("JIRA_EMAIL", "").strip()
    api_token = os.getenv("JIRA_API_TOKEN", "").strip()

    if not site_url or not email or not api_token:
        missing = ", ".join(jira_missing_env_vars())
        raise JiraConfigError(f"Missing Jira configuration: {missing}")

    return JiraConfig(site_url=site_url, email=email, api_token=api_token)


def fetch_jira_issue(issue_key: str) -> dict[str, Any]:
    config = load_jira_config()
    fields = [
        "summary",
        "description",
        "status",
        "priority",
        "issuetype",
        "created",
        "updated",
        "reporter",
        "assignee",
        "labels",
        "components",
    ]
    path = f"/rest/api/3/issue/{quote(issue_key.strip())}"
    query = urlencode({"fields": ",".join(fields)})
    issue = _jira_get(config, f"{path}?{query}", issue_key)
    return _shape_issue(issue, config.site_url)


def jira_issue_to_ticket(issue: dict[str, Any]) -> dict[str, Any]:
    fields = issue.get("fields", {})
    summary = str(fields.get("summary") or "Customer escalation")
    description = _plain_text(fields.get("description"))
    labels = [str(label) for label in fields.get("labels") or []]
    components = fields.get("components") or []
    component = _component_name(components, labels, summary, description)
    customer = _customer_name(fields, labels, summary, description)
    sentry_error = _sentry_error(labels, summary, description, component)
    assignee = _user_name(fields.get("assignee"))

    return {
        "id": str(issue.get("key") or issue.get("id") or "JIRA-UNKNOWN"),
        "raw_customer": customer,
        "component": component,
        "summary": summary if not description else f"{summary} {description[:320]}",
        "date": str(fields.get("created") or "")[:10],
        "sentry_error": sentry_error,
        "source": "jira",
        "source_url": issue.get("url"),
        "assignee": assignee,
    }


def _jira_get(config: JiraConfig, path: str, issue_key: str) -> dict[str, Any]:
    credentials = f"{config.email}:{config.api_token}".encode("utf-8")
    auth = base64.b64encode(credentials).decode("ascii")
    request = Request(
        f"{config.site_url}{path}",
        headers={
            "Accept": "application/json",
            "Authorization": f"Basic {auth}",
            "User-Agent": "throughline-demo/1.0",
        },
    )

    try:
        with urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as error:
        if error.code == 404:
            raise JiraIssueNotFound(f"Jira issue {issue_key} was not found.") from error
        detail = error.read().decode("utf-8", errors="replace")
        raise JiraRequestError(f"Jira returned {error.code}: {detail[:500]}") from error
    except URLError as error:
        raise JiraRequestError(f"Could not reach Jira: {error.reason}") from error


def _shape_issue(issue: dict[str, Any], site_url: str) -> dict[str, Any]:
    shaped = dict(issue)
    if issue.get("key"):
        shaped["url"] = f"{site_url}/browse/{issue['key']}"
    return shaped


def _component_name(
    components: list[dict[str, Any]],
    labels: list[str],
    summary: str,
    description: str,
) -> str:
    if components:
        name = components[0].get("name")
        if name:
            return str(name)

    for label in labels:
        lowered = label.lower()
        if lowered.startswith("component:"):
            return _clean_value(label.split(":", 1)[1])
        if lowered.startswith(("component-", "component_")):
            return _clean_value(re.sub(r"^component[-_]", "", label, flags=re.I))

    text = f"{summary}\n{description}"
    match = re.search(r"\b(?:component|service|area)\s*[:=-]\s*([A-Za-z0-9 ._-]+)", text, re.I)
    if match:
        return _clean_value(match.group(1))

    haystack = " ".join([summary, description, *labels]).lower()
    for candidate in (
        "PaymentService",
        "SearchService",
        "AuthService",
        "BillingService",
        "Frontend",
    ):
        if candidate.lower() in haystack:
            return candidate
    return "Unknown component"


def _customer_name(
    fields: dict[str, Any],
    labels: list[str],
    summary: str,
    description: str,
) -> str:
    for label in labels:
        lowered = label.lower()
        if lowered.startswith("customer:"):
            return _clean_value(label.split(":", 1)[1])
        if lowered.startswith(("customer-", "customer_")):
            return _clean_value(re.sub(r"^customer[-_]", "", label, flags=re.I))

    text = f"{summary}\n{description}"
    match = re.search(r"\b(?:customer|account)\s*[:=-]\s*([A-Za-z0-9 ._-]+)", text, re.I)
    if match:
        return _clean_value(match.group(1))
    if re.search(r"\bacme\b", text, re.I):
        return "Acme Corp"

    reporter = fields.get("reporter") or {}
    if isinstance(reporter, dict):
        name = reporter.get("displayName") or reporter.get("emailAddress")
        if name:
            return str(name)
    return "Unknown customer"


def _user_name(value: Any) -> str | None:
    if not isinstance(value, dict):
        return None
    name = value.get("displayName") or value.get("emailAddress") or value.get("name")
    return str(name) if name else None


def _sentry_error(
    labels: list[str],
    summary: str,
    description: str,
    component: str,
) -> dict[str, str] | None:
    service = component
    error_class: str | None = None
    for label in labels:
        lowered = label.lower()
        if lowered.startswith("sentry:"):
            error_class = _clean_value(label.split(":", 1)[1])
        if lowered.startswith("service:"):
            service = _clean_value(label.split(":", 1)[1])

    if error_class:
        return {"error_class": error_class, "service": service}

    text = f"{summary}\n{description}"
    match = re.search(r"\b([A-Z][A-Za-z0-9]+(?:Timeout|Error|Exception|Race))\b", text)
    if match:
        return {"error_class": match.group(1), "service": service}
    return None


def _plain_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        parts: list[str] = []
        if value.get("text"):
            parts.append(str(value["text"]))
        for child in value.get("content") or []:
            text = _plain_text(child)
            if text:
                parts.append(text)
        return " ".join(parts)
    if isinstance(value, list):
        return " ".join(text for item in value if (text := _plain_text(item)))
    return str(value)


def _clean_value(value: str) -> str:
    return value.replace("-", " ").replace("_", " ").strip()
