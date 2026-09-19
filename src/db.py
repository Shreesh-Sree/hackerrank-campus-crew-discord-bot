from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

log = logging.getLogger("hrcc.db")

_ROOT = Path(__file__).resolve().parent.parent
_DB_PATH = _ROOT / "data" / "hrcc.db"

_conn: sqlite3.Connection | None = None

_TICKET_COUNTER_START = 100


def _get_conn() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        _conn = sqlite3.connect(str(_DB_PATH), check_same_thread=False)
        _conn.row_factory = sqlite3.Row
        _conn.execute("PRAGMA journal_mode=WAL")
        _conn.execute("PRAGMA foreign_keys=ON")
    return _conn


def init_db() -> None:
    conn = _get_conn()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS escalation_tickets (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            ticket_code     TEXT    NOT NULL UNIQUE,
            channel_id      INTEGER NOT NULL,
            message_id      INTEGER NOT NULL,
            author_id       INTEGER NOT NULL,
            author_name     TEXT    NOT NULL,
            category        TEXT    NOT NULL CHECK(category IN ('OPS','TECH','DESIGN')),
            urgency         TEXT    NOT NULL CHECK(urgency IN ('P0','P1','P2')),
            poc_name        TEXT    NOT NULL,
            poc_id          TEXT    NOT NULL DEFAULT '',
            status          TEXT    NOT NULL DEFAULT 'PENDING'
                            CHECK(status IN ('PENDING','ACKNOWLEDGED','RESOLVED')),
            description     TEXT    NOT NULL DEFAULT '',
            resolution_notes TEXT   NOT NULL DEFAULT '',
            created_at      TEXT    NOT NULL,
            updated_at      TEXT    NOT NULL
        );

        CREATE TABLE IF NOT EXISTS ambassador_events (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            ambassador_id   INTEGER NOT NULL,
            ambassador_name TEXT    NOT NULL,
            college_name    TEXT    NOT NULL DEFAULT '',
            event_name      TEXT    NOT NULL,
            event_date      TEXT    NOT NULL DEFAULT '',
            platform        TEXT    NOT NULL DEFAULT '',
            participant_count INTEGER NOT NULL DEFAULT 0,
            reward_tier     TEXT    NOT NULL DEFAULT '',
            merch_eligible  INTEGER NOT NULL DEFAULT 0,
            csv_sha256      TEXT    NOT NULL DEFAULT '',
            created_at      TEXT    NOT NULL
        );
    """)
    conn.commit()
    log.info("Database initialized at %s", _DB_PATH)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _next_ticket_code() -> str:
    conn = _get_conn()
    row = conn.execute("SELECT MAX(id) AS m FROM escalation_tickets").fetchone()
    next_id = (row["m"] or 0) + 1
    return f"HRCC-{_TICKET_COUNTER_START + next_id}"


def create_ticket(
    *,
    channel_id: int,
    message_id: int,
    author_id: int,
    author_name: str,
    category: str,
    urgency: str,
    poc_name: str,
    poc_id: str = "",
    description: str = "",
) -> dict[str, Any]:
    conn = _get_conn()
    now = _now_iso()
    ticket_code = _next_ticket_code()

    conn.execute(
        """INSERT INTO escalation_tickets
           (ticket_code, channel_id, message_id, author_id, author_name,
            category, urgency, poc_name, poc_id, status, description,
            resolution_notes, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'PENDING', ?, '', ?, ?)""",
        (ticket_code, channel_id, message_id, author_id, author_name,
         category, urgency, poc_name, poc_id, description, now, now),
    )
    conn.commit()
    log.info("Created ticket %s [%s/%s] for %s", ticket_code, category, urgency, author_name)
    return get_ticket(ticket_code)  # type: ignore[return-value]


def update_ticket_status(
    ticket_code: str,
    status: str,
    *,
    resolution_notes: str = "",
) -> dict[str, Any] | None:
    conn = _get_conn()
    now = _now_iso()

    if resolution_notes:
        conn.execute(
            "UPDATE escalation_tickets SET status=?, resolution_notes=?, updated_at=? WHERE ticket_code=?",
            (status, resolution_notes, now, ticket_code),
        )
    else:
        conn.execute(
            "UPDATE escalation_tickets SET status=?, updated_at=? WHERE ticket_code=?",
            (status, now, ticket_code),
        )
    conn.commit()
    log.info("Ticket %s -> %s", ticket_code, status)
    return get_ticket(ticket_code)


def get_ticket(ticket_code: str) -> dict[str, Any] | None:
    conn = _get_conn()
    row = conn.execute(
        "SELECT * FROM escalation_tickets WHERE ticket_code=?", (ticket_code,)
    ).fetchone()
    if row is None:
        return None
    return dict(row)


def get_recent_tickets(author_id: int, category: str, hours: int = 2) -> list[dict[str, Any]]:
    conn = _get_conn()
    cutoff = datetime.now(timezone.utc).isoformat()
    rows = conn.execute(
        """SELECT * FROM escalation_tickets
           WHERE author_id=? AND category=? AND status != 'RESOLVED'
           AND created_at >= datetime(?, '-' || ? || ' hours')
           ORDER BY created_at DESC""",
        (author_id, category, cutoff, hours),
    ).fetchall()
    return [dict(r) for r in rows]


def record_event_submission(
    *,
    ambassador_id: int,
    ambassador_name: str,
    college_name: str = "",
    event_name: str,
    event_date: str = "",
    platform: str = "",
    participant_count: int = 0,
    reward_tier: str = "",
    merch_eligible: bool = False,
    csv_sha256: str = "",
) -> dict[str, Any]:
    conn = _get_conn()
    now = _now_iso()

    conn.execute(
        """INSERT INTO ambassador_events
           (ambassador_id, ambassador_name, college_name, event_name, event_date,
            platform, participant_count, reward_tier, merch_eligible, csv_sha256, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (ambassador_id, ambassador_name, college_name, event_name, event_date,
         platform, participant_count, reward_tier, 1 if merch_eligible else 0,
         csv_sha256, now),
    )
    conn.commit()
    row_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    row = conn.execute("SELECT * FROM ambassador_events WHERE id=?", (row_id,)).fetchone()
    return dict(row)


def close_db() -> None:
    global _conn
    if _conn is not None:
        _conn.close()
        _conn = None
