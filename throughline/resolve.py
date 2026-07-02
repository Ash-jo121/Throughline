from __future__ import annotations


CUSTOMER_ALIASES = {
    "acme_corp": "Acme Corp",
    "acme corp ltd": "Acme Corp",
    "acme": "Acme Corp",
    "globex inc": "Globex",
    "initech llc": "Initech",
}


def resolve_customer(raw: str) -> str:
    """Resolve a known customer alias to its canonical account name."""

    stripped = raw.strip()
    return CUSTOMER_ALIASES.get(stripped.lower(), stripped)
