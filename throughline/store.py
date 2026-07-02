from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from throughline.config import BRIEF_DB_PATH
from throughline.synthesize import IncidentBrief


def persist_brief(brief: IncidentBrief) -> str:
    _init_db()
    created_at = datetime.now(UTC).isoformat()
    with _connect() as connection:
        connection.execute(
            """
            INSERT OR REPLACE INTO briefs(brief_id, payload, created_at)
            VALUES (?, ?, ?)
            """,
            (brief.brief_id, brief.model_dump_json(), created_at),
        )
    return brief.brief_id


def get_brief(brief_id: str) -> IncidentBrief | None:
    _init_db()
    with _connect() as connection:
        row = connection.execute(
            "SELECT payload FROM briefs WHERE brief_id = ?",
            (brief_id,),
        ).fetchone()
    if row is None:
        return None
    return IncidentBrief.model_validate_json(row["payload"])


def persist_feedback(brief_id: str, verdict: str, note: str | None = None) -> str:
    _init_db()
    feedback_id = str(uuid4())
    with _connect() as connection:
        connection.execute(
            """
            INSERT INTO feedback(feedback_id, brief_id, verdict, note, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (feedback_id, brief_id, verdict, note, datetime.now(UTC).isoformat()),
        )
    return feedback_id


def persist_forget_request(customer_name: str) -> str:
    _init_db()
    request_id = str(uuid4())
    with _connect() as connection:
        connection.execute(
            """
            INSERT INTO forget_requests(request_id, customer_name, created_at, status)
            VALUES (?, ?, ?, ?)
            """,
            (request_id, customer_name, datetime.now(UTC).isoformat(), "pending"),
        )
    return request_id


def list_feedback() -> list[dict[str, Any]]:
    _init_db()
    with _connect() as connection:
        rows = connection.execute(
            "SELECT feedback_id, brief_id, verdict, note, created_at FROM feedback"
        ).fetchall()
    return [dict(row) for row in rows]


def list_forget_requests() -> list[dict[str, Any]]:
    _init_db()
    with _connect() as connection:
        rows = connection.execute(
            "SELECT request_id, customer_name, created_at, status FROM forget_requests"
        ).fetchall()
    return [dict(row) for row in rows]


def _connect() -> sqlite3.Connection:
    connection = sqlite3.connect(_db_path())
    connection.row_factory = sqlite3.Row
    return connection


def _db_path() -> Path:
    BRIEF_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    return BRIEF_DB_PATH


def _init_db() -> None:
    with _connect() as connection:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS briefs (
                brief_id TEXT PRIMARY KEY,
                payload TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS feedback (
                feedback_id TEXT PRIMARY KEY,
                brief_id TEXT NOT NULL,
                verdict TEXT NOT NULL CHECK (verdict IN ('up', 'down')),
                note TEXT,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS forget_requests (
                request_id TEXT PRIMARY KEY,
                customer_name TEXT NOT NULL,
                created_at TEXT NOT NULL,
                status TEXT NOT NULL
            );
            """
        )
