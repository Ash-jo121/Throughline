from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from throughline.config import BRIEF_DB_PATH
from throughline.synthesize import IncidentBrief


@dataclass(frozen=True)
class BriefMemoryRefs:
    session_id: str | None
    qa_id: str | None


def persist_brief(
    brief: IncidentBrief,
    *,
    session_id: str | None = None,
    qa_id: str | None = None,
) -> str:
    _init_db()
    created_at = datetime.now(UTC).isoformat()
    with _connect() as connection:
        _delete_existing_incident_ref(connection, brief.incident_ref)
        connection.execute(
            """
            INSERT OR REPLACE INTO briefs(
                brief_id, incident_ref, payload, created_at, session_id, qa_id
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                brief.brief_id,
                brief.incident_ref,
                brief.model_dump_json(),
                created_at,
                session_id,
                qa_id,
            ),
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


def get_latest_brief() -> IncidentBrief | None:
    _init_db()
    with _connect() as connection:
        row = connection.execute(
            """
            SELECT payload FROM briefs
            ORDER BY created_at DESC
            LIMIT 1
            """,
        ).fetchone()
    if row is None:
        return None
    return IncidentBrief.model_validate_json(row["payload"])


def get_all_briefs() -> list[IncidentBrief]:
    _init_db()
    with _connect() as connection:
        rows = connection.execute(
            """
            SELECT payload FROM briefs
            ORDER BY created_at DESC
            """,
        ).fetchall()
    briefs = [IncidentBrief.model_validate_json(row["payload"]) for row in rows]
    seen: set[str] = set()
    deduped: list[IncidentBrief] = []
    for brief in briefs:
        if brief.incident_ref in seen:
            continue
        seen.add(brief.incident_ref)
        deduped.append(brief)
    return deduped


def get_brief_memory_refs(brief_id: str) -> BriefMemoryRefs | None:
    _init_db()
    with _connect() as connection:
        row = connection.execute(
            "SELECT session_id, qa_id FROM briefs WHERE brief_id = ?",
            (brief_id,),
        ).fetchone()
    if row is None:
        return None
    return BriefMemoryRefs(session_id=row["session_id"], qa_id=row["qa_id"])


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


def mark_forget_request_done(request_id: str, detail: str | None = None) -> None:
    _init_db()
    with _connect() as connection:
        connection.execute(
            """
            UPDATE forget_requests
            SET status = ?, detail = ?, completed_at = ?
            WHERE request_id = ?
            """,
            ("done", detail, datetime.now(UTC).isoformat(), request_id),
        )


def persist_customer_data(
    customer_name: str,
    data_id: str,
    source_ref: str,
) -> None:
    _init_db()
    with _connect() as connection:
        connection.execute(
            """
            INSERT OR IGNORE INTO customer_data(customer_name, data_id, source_ref, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (customer_name, data_id, source_ref, datetime.now(UTC).isoformat()),
        )


def list_customer_data_ids(customer_name: str) -> list[str]:
    _init_db()
    with _connect() as connection:
        rows = connection.execute(
            """
            SELECT data_id FROM customer_data
            WHERE customer_name = ? AND forgotten_at IS NULL
            ORDER BY created_at
            """,
            (customer_name,),
        ).fetchall()
    return [str(row["data_id"]) for row in rows]


def mark_customer_data_forgotten(customer_name: str, data_ids: list[str]) -> None:
    if not data_ids:
        return

    _init_db()
    placeholders = ",".join("?" for _ in data_ids)
    with _connect() as connection:
        connection.execute(
            f"""
            UPDATE customer_data
            SET forgotten_at = ?
            WHERE customer_name = ? AND data_id IN ({placeholders})
            """,
            [datetime.now(UTC).isoformat(), customer_name, *data_ids],
        )


def delete_customer_briefs(customer_name: str) -> int:
    _init_db()
    with _connect() as connection:
        rows = connection.execute("SELECT rowid, payload FROM briefs").fetchall()
        delete_rowids: list[int] = []
        update_rows: list[tuple[str, int]] = []
        for row in rows:
            try:
                brief = IncidentBrief.model_validate_json(row["payload"])
            except Exception:
                continue
            rowid = int(row["rowid"])
            if brief.customer == customer_name:
                delete_rowids.append(rowid)
                continue
            if customer_name in brief.also_affected:
                brief.also_affected = [
                    customer for customer in brief.also_affected if customer != customer_name
                ]
                update_rows.append((brief.model_dump_json(), rowid))

        for payload, rowid in update_rows:
            connection.execute("UPDATE briefs SET payload = ? WHERE rowid = ?", (payload, rowid))

        if delete_rowids:
            placeholders = ",".join("?" for _ in delete_rowids)
            connection.execute(
                f"DELETE FROM briefs WHERE rowid IN ({placeholders})",
                delete_rowids,
            )
        return len(delete_rowids)


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
                incident_ref TEXT,
                payload TEXT NOT NULL,
                created_at TEXT NOT NULL,
                session_id TEXT,
                qa_id TEXT
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
                status TEXT NOT NULL,
                completed_at TEXT,
                detail TEXT
            );

            CREATE TABLE IF NOT EXISTS customer_data (
                customer_name TEXT NOT NULL,
                data_id TEXT NOT NULL,
                source_ref TEXT NOT NULL,
                created_at TEXT NOT NULL,
                forgotten_at TEXT,
                PRIMARY KEY (customer_name, data_id)
            );
            """
        )
        _ensure_columns(
            connection,
            "briefs",
            {
                "incident_ref": "TEXT",
                "session_id": "TEXT",
                "qa_id": "TEXT",
            },
        )
        _ensure_columns(
            connection,
            "forget_requests",
            {
                "completed_at": "TEXT",
                "detail": "TEXT",
            },
        )


def _ensure_columns(
    connection: sqlite3.Connection,
    table_name: str,
    columns: dict[str, str],
) -> None:
    existing = {
        str(row["name"])
        for row in connection.execute(f"PRAGMA table_info({table_name})").fetchall()
    }
    for name, definition in columns.items():
        if name not in existing:
            connection.execute(f"ALTER TABLE {table_name} ADD COLUMN {name} {definition}")


def _delete_existing_incident_ref(connection: sqlite3.Connection, incident_ref: str) -> None:
    rows = connection.execute("SELECT rowid, incident_ref, payload FROM briefs").fetchall()
    rowids: list[int] = []
    for row in rows:
        if row["incident_ref"] == incident_ref:
            rowids.append(int(row["rowid"]))
            continue
        try:
            brief = IncidentBrief.model_validate_json(row["payload"])
        except Exception:
            continue
        if brief.incident_ref == incident_ref:
            rowids.append(int(row["rowid"]))

    if not rowids:
        return

    placeholders = ",".join("?" for _ in rowids)
    connection.execute(f"DELETE FROM briefs WHERE rowid IN ({placeholders})", rowids)
