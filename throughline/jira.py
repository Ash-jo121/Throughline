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


class JiraConfigurationError(RuntimeError):
    pass


class JiraRequestError(RuntimeError):
    pass


@dataclass(frozen=True)
class JiraConfig:
    site_url: str
    email: str
    api_token: str


def jira_configured() -> bool:
    return all(os.getenv(key) for key in ("JIRA_SITE_URL", "JIRA_EMAIL", "JIRA_API_TOKEN"))


def load_jira_config() -> JiraConfig:
    site_url = os.getenv("JIRA_SITE_URL", "").strip().rstrip("/")
    email = os.getenv("JIRA_EMAIL", "").strip()
    api_token = os.getenv("JIRA_API_TOKEN", "").strip()

    if not site_url or not email or not api_token:
        raise JiraConfigurationError(
            "Set JIRA_SITE_URL, JIRA_EMAIL, and JIRA_API_TOKEN to enable Jira Cloud import."
        )

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
        "labels",
        "components",
    ]
    path = f"/rest/api/3/issue/{quote(issue_key.strip())}"
    query = urlencode({"fields": ",".join(fields)})
    issue = _jira_get(config, f"{path}?{query}")
    return _shape_issue(issue, config.site_url)


def jira_issue_to_ticket(issue: dict[str, Any]) -> dict[str, Any]:
    fields = issue.get("fields", {})
    summary = str(fields.get("summary") or "Customer escalation")
    description = _plain_text(fields.get("description"))
    labels = [str(label) for label in fields.get("labels") or []]
    components = fields.get("components") or []
    component = _component_name(components, labels, summary, description)
    customer = _customer_name(labels, summary, description)
    sentry_error = _sentry_error(labels, summary, description, component)

    return {
        "id": issue.get("key") or issue.get("id") or "JIRA-UNKNOWN",
        "raw_customer": customer,
        "component": component,
        "summary": summary if not description else f"{summary} {description[:320]}",
        "date": str(fields.get("created") or ""),
        "sentry_error": sentry_error,
        "source": "jira",
        "source_url": issue.get("url"),
    }


def _jira_get(config: JiraConfig, path: str) -> dict[str, Any]:
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
            return label.split(":", 1)[1].replace("-", " ").strip()
        if lowered.startswith(("component-", "component_")):
            return re.sub(r"^component[-_]", "", label, flags=re.I).replace("-", " ").strip()

    text = f"{summary}\n{description}"
    match = re.search(r"\b(?:component|service|area)\s*[:=-]\s*([A-Za-z0-9 ._-]+)", text, re.I)
    if match:
        return match.group(1).strip()

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


def _customer_name(labels: list[str], summary: str, description: str) -> str:
    for label in labels:
        lowered = label.lower()
        if lowered.startswith("customer:"):
            return label.split(":", 1)[1].replace("-", " ").strip()
        if lowered.startswith(("customer-", "customer_")):
            return re.sub(r"^customer[-_]", "", label, flags=re.I).replace("-", " ").strip()

    text = f"{summary}\n{description}"
    match = re.search(r"\b(?:customer|account)\s*[:=-]\s*([A-Za-z0-9 ._-]+)", text, re.I)
    if match:
        return match.group(1).strip()
    if re.search(r"\bacme\b", text, re.I):
        return "Acme Corp"
    return "Unknown customer"


def _sentry_error(
    labels: list[str],
    summary: str,
    description: str,
    component: str,
) -> dict[str, str] | None:
    for label in labels:
        if label.lower().startswith("sentry:"):
            return {"error_class": label.split(":", 1)[1].strip(), "service": component}

    text = f"{summary}\n{description}"
    match = re.search(r"\b([A-Z][A-Za-z0-9]+(?:Timeout|Error|Exception|Race))\b", text)
    if match:
        return {"error_class": match.group(1), "service": component}
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
