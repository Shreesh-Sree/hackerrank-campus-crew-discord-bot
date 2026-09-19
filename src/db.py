from __future__ import annotations

import logging
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.config import settings

log = logging.getLogger("hrcc.db")

_ROOT = Path(__file__).resolve().parent.parent
_SQLITE_PATH: Path = _ROOT / settings.db_path

_local = threading.local()

_TICKET_COUNTER_START = 100

_using_postgres: bool = False


def _is_postgres() -> bool:
    url = settings.database_url
    return url.startswith("postgresql://") or url.startswith("postgres://")


def _get_sqlite_conn() -> sqlite3.Connection:
    conn: sqlite3.Connection | None = getattr(_local, "sqlite_conn", None)
    if conn is not None:
        try:
            conn.execute("SELECT 1")
            return conn
        except sqlite3.ProgrammingError:
            conn = None

    _SQLITE_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(_SQLITE_PATH), timeout=10.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=5000")
    _local.sqlite_conn = conn
    return conn


def _get_pg_conn():
    conn = getattr(_local, "pg_conn", None)
    if conn is not None:
        try:
            conn.execute("SELECT 1")
            return conn
        except Exception:
            try:
                conn.close()
            except Exception:
                pass
            conn = None

    import psycopg
    from psycopg.rows import dict_row

    conn = psycopg.connect(settings.database_url, row_factory=dict_row, autocommit=False)
    _local.pg_conn = conn
    return conn


def _ph(n: int = 1) -> str:
    if _using_postgres:
        return ", ".join(["%s"] * n)
    return ", ".join(["?"] * n)


def _p(*args: Any) -> tuple[Any, ...]:
    return args


def _execute(sql: str, params: tuple = ()) -> None:
    if _using_postgres:
        sql = sql.replace("?", "%s")
        conn = _get_pg_conn()
        conn.execute(sql, params)
        conn.commit()
    else:
        conn = _get_sqlite_conn()
        conn.execute(sql, params)
        conn.commit()


def _fetchone(sql: str, params: tuple = ()) -> dict[str, Any] | None:
    if _using_postgres:
        sql = sql.replace("?", "%s")
        conn = _get_pg_conn()
        cur = conn.execute(sql, params)
        row = cur.fetchone()
        return dict(row) if row else None
    else:
        conn = _get_sqlite_conn()
        row = conn.execute(sql, params).fetchone()
        return dict(row) if row else None


def _fetchall(sql: str, params: tuple = ()) -> list[dict[str, Any]]:
    if _using_postgres:
        sql = sql.replace("?", "%s")
        conn = _get_pg_conn()
        cur = conn.execute(sql, params)
        return [dict(r) for r in cur.fetchall()]
    else:
        conn = _get_sqlite_conn()
        rows = conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]


_SQLITE_SCHEMA = """
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

    CREATE TABLE IF NOT EXISTS ambassador_profiles (
        ambassador_id   INTEGER PRIMARY KEY,
        ambassador_name TEXT    NOT NULL,
        college_name    TEXT    NOT NULL DEFAULT '',
        current_stage   TEXT    NOT NULL DEFAULT 'PLANNING'
                        CHECK(current_stage IN ('PLANNING','SETUP','OUTREACH','LIVE','REWARDS')),
        notes           TEXT    NOT NULL DEFAULT '',
        updated_at      TEXT    NOT NULL
    );

    CREATE TABLE IF NOT EXISTS conversation_turns (
        id        INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id   INTEGER NOT NULL,
        role      TEXT    NOT NULL CHECK(role IN ('user','assistant')),
        content   TEXT    NOT NULL,
        timestamp TEXT    NOT NULL
    );

    CREATE INDEX IF NOT EXISTS idx_tickets_author_cat
        ON escalation_tickets(author_id, category, status);
    CREATE INDEX IF NOT EXISTS idx_tickets_code
        ON escalation_tickets(ticket_code);
    CREATE INDEX IF NOT EXISTS idx_events_ambassador
        ON ambassador_events(ambassador_id);
    CREATE INDEX IF NOT EXISTS idx_conv_user
        ON conversation_turns(user_id, timestamp);
"""

_PG_SCHEMA = """
    CREATE TABLE IF NOT EXISTS escalation_tickets (
        id              SERIAL PRIMARY KEY,
        ticket_code     TEXT    NOT NULL UNIQUE,
        channel_id      BIGINT  NOT NULL,
        message_id      BIGINT  NOT NULL,
        author_id       BIGINT  NOT NULL,
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
        id              SERIAL PRIMARY KEY,
        ambassador_id   BIGINT  NOT NULL,
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

    CREATE TABLE IF NOT EXISTS ambassador_profiles (
        ambassador_id   BIGINT PRIMARY KEY,
        ambassador_name TEXT    NOT NULL,
        college_name    TEXT    NOT NULL DEFAULT '',
        current_stage   TEXT    NOT NULL DEFAULT 'PLANNING'
                        CHECK(current_stage IN ('PLANNING','SETUP','OUTREACH','LIVE','REWARDS')),
        notes           TEXT    NOT NULL DEFAULT '',
        updated_at      TEXT    NOT NULL
    );

    CREATE TABLE IF NOT EXISTS conversation_turns (
        id        SERIAL PRIMARY KEY,
        user_id   BIGINT  NOT NULL,
        role      TEXT    NOT NULL CHECK(role IN ('user','assistant')),
        content   TEXT    NOT NULL,
        timestamp TEXT    NOT NULL
    );

    CREATE INDEX IF NOT EXISTS idx_tickets_author_cat
        ON escalation_tickets(author_id, category, status);
    CREATE INDEX IF NOT EXISTS idx_tickets_code
        ON escalation_tickets(ticket_code);
    CREATE INDEX IF NOT EXISTS idx_events_ambassador
        ON ambassador_events(ambassador_id);
    CREATE INDEX IF NOT EXISTS idx_conv_user
        ON conversation_turns(user_id, timestamp);
"""


def init_db() -> None:
    global _using_postgres

    if _is_postgres():
        _using_postgres = True
        conn = _get_pg_conn()
        for stmt in _PG_SCHEMA.strip().split(";"):
            stmt = stmt.strip()
            if stmt:
                conn.execute(stmt)
        conn.commit()
        log.info("PostgreSQL database initialized at %s", settings.database_url.split("@")[-1])
    else:
        _using_postgres = False
        conn = _get_sqlite_conn()
        conn.executescript(_SQLITE_SCHEMA)
        conn.commit()
        log.info("SQLite database initialized at %s", _SQLITE_PATH)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _next_ticket_code() -> str:
    row = _fetchone("SELECT MAX(id) AS m FROM escalation_tickets")
    next_id = ((row["m"] or 0) if row else 0) + 1
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
    now = _now_iso()
    ticket_code = _next_ticket_code()

    _execute(
        """INSERT INTO escalation_tickets
           (ticket_code, channel_id, message_id, author_id, author_name,
            category, urgency, poc_name, poc_id, status, description,
            resolution_notes, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'PENDING', ?, '', ?, ?)""",
        (ticket_code, channel_id, message_id, author_id, author_name,
         category, urgency, poc_name, poc_id, description, now, now),
    )
    log.info("Created ticket %s [%s/%s] for %s", ticket_code, category, urgency, author_name)
    return get_ticket(ticket_code)  # type: ignore[return-value]


def update_ticket_status(
    ticket_code: str,
    status: str,
    *,
    resolution_notes: str = "",
) -> dict[str, Any] | None:
    now = _now_iso()

    if resolution_notes:
        _execute(
            "UPDATE escalation_tickets SET status=?, resolution_notes=?, updated_at=? WHERE ticket_code=?",
            (status, resolution_notes, now, ticket_code),
        )
    else:
        _execute(
            "UPDATE escalation_tickets SET status=?, updated_at=? WHERE ticket_code=?",
            (status, now, ticket_code),
        )
    log.info("Ticket %s -> %s", ticket_code, status)
    return get_ticket(ticket_code)


def get_ticket(ticket_code: str) -> dict[str, Any] | None:
    return _fetchone("SELECT * FROM escalation_tickets WHERE ticket_code=?", (ticket_code,))


def get_recent_tickets(author_id: int, category: str, hours: int = 2) -> list[dict[str, Any]]:
    if _using_postgres:
        return _fetchall(
            """SELECT * FROM escalation_tickets
               WHERE author_id=? AND category=? AND status != 'RESOLVED'
               AND created_at >= (NOW() - INTERVAL '1 hour' * ?)::text
               ORDER BY created_at DESC""",
            (author_id, category, hours),
        )
    else:
        cutoff = datetime.now(timezone.utc).isoformat()
        return _fetchall(
            """SELECT * FROM escalation_tickets
               WHERE author_id=? AND category=? AND status != 'RESOLVED'
               AND created_at >= datetime(?, '-' || ? || ' hours')
               ORDER BY created_at DESC""",
            (author_id, category, cutoff, hours),
        )


def get_ticket_stats() -> dict[str, int]:
    rows = _fetchall("SELECT status, COUNT(*) AS cnt FROM escalation_tickets GROUP BY status")
    stats: dict[str, int] = {"PENDING": 0, "ACKNOWLEDGED": 0, "RESOLVED": 0}
    for row in rows:
        stats[row["status"]] = row["cnt"]
    stats["total"] = sum(stats.values())
    return stats


def get_ambassador_events(ambassador_id: int) -> list[dict[str, Any]]:
    return _fetchall(
        "SELECT * FROM ambassador_events WHERE ambassador_id=? ORDER BY created_at DESC",
        (ambassador_id,),
    )


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
    now = _now_iso()

    _execute(
        """INSERT INTO ambassador_events
           (ambassador_id, ambassador_name, college_name, event_name, event_date,
            platform, participant_count, reward_tier, merch_eligible, csv_sha256, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (ambassador_id, ambassador_name, college_name, event_name, event_date,
         platform, participant_count, reward_tier, 1 if merch_eligible else 0,
         csv_sha256, now),
    )

    if _using_postgres:
        row = _fetchone(
            "SELECT * FROM ambassador_events WHERE ambassador_id=? AND created_at=?",
            (ambassador_id, now),
        )
    else:
        conn = _get_sqlite_conn()
        row_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        row = _fetchone("SELECT * FROM ambassador_events WHERE id=?", (row_id,))
    return row or {}


def upsert_ambassador_profile(
    *,
    ambassador_id: int,
    ambassador_name: str,
    college_name: str = "",
    current_stage: str = "PLANNING",
    notes: str = "",
) -> dict[str, Any]:
    now = _now_iso()

    if _using_postgres:
        _execute(
            """INSERT INTO ambassador_profiles (ambassador_id, ambassador_name, college_name, current_stage, notes, updated_at)
               VALUES (?, ?, ?, ?, ?, ?)
               ON CONFLICT(ambassador_id) DO UPDATE SET
                 ambassador_name=EXCLUDED.ambassador_name,
                 college_name=CASE WHEN EXCLUDED.college_name='' THEN ambassador_profiles.college_name ELSE EXCLUDED.college_name END,
                 current_stage=EXCLUDED.current_stage,
                 notes=CASE WHEN EXCLUDED.notes='' THEN ambassador_profiles.notes ELSE EXCLUDED.notes END,
                 updated_at=EXCLUDED.updated_at""",
            (ambassador_id, ambassador_name, college_name, current_stage, notes, now),
        )
    else:
        _execute(
            """INSERT INTO ambassador_profiles (ambassador_id, ambassador_name, college_name, current_stage, notes, updated_at)
               VALUES (?, ?, ?, ?, ?, ?)
               ON CONFLICT(ambassador_id) DO UPDATE SET
                 ambassador_name=excluded.ambassador_name,
                 college_name=CASE WHEN excluded.college_name='' THEN ambassador_profiles.college_name ELSE excluded.college_name END,
                 current_stage=excluded.current_stage,
                 notes=CASE WHEN excluded.notes='' THEN ambassador_profiles.notes ELSE excluded.notes END,
                 updated_at=excluded.updated_at""",
            (ambassador_id, ambassador_name, college_name, current_stage, notes, now),
        )
    return get_ambassador_profile(ambassador_id) or {}


def get_ambassador_profile(ambassador_id: int) -> dict[str, Any] | None:
    return _fetchone("SELECT * FROM ambassador_profiles WHERE ambassador_id=?", (ambassador_id,))


def update_ambassador_stage(ambassador_id: int, stage: str) -> dict[str, Any] | None:
    now = _now_iso()
    _execute(
        "UPDATE ambassador_profiles SET current_stage=?, updated_at=? WHERE ambassador_id=?",
        (stage, now, ambassador_id),
    )
    return get_ambassador_profile(ambassador_id)


def save_conversation_turn(user_id: int, role: str, content: str) -> None:
    now = _now_iso()
    _execute(
        "INSERT INTO conversation_turns (user_id, role, content, timestamp) VALUES (?, ?, ?, ?)",
        (user_id, role, content, now),
    )


def get_conversation_turns(user_id: int, limit: int = 16) -> list[dict[str, str]]:
    rows = _fetchall(
        "SELECT role, content FROM conversation_turns WHERE user_id=? ORDER BY timestamp DESC LIMIT ?",
        (user_id, limit),
    )
    return [{"role": r["role"], "content": r["content"]} for r in reversed(rows)]


def get_events_in_window(hours_from: int, hours_to: int) -> list[dict[str, Any]]:
    if _using_postgres:
        return _fetchall(
            """SELECT * FROM ambassador_events
               WHERE event_date != ''
               AND event_date::timestamp BETWEEN NOW() + (? || ' hours')::interval
               AND NOW() + (? || ' hours')::interval
               ORDER BY event_date""",
            (str(hours_from), str(hours_to)),
        )
    else:
        return _fetchall(
            """SELECT * FROM ambassador_events
               WHERE event_date != ''
               AND datetime(event_date) BETWEEN datetime('now', ? || ' hours')
               AND datetime('now', ? || ' hours')
               ORDER BY event_date""",
            (str(hours_from), str(hours_to)),
        )


def get_monthly_stats() -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0).isoformat()

    event_row = _fetchone(
        "SELECT COUNT(*) as cnt, COALESCE(SUM(participant_count),0) as total_p "
        "FROM ambassador_events WHERE created_at >= ?",
        (month_start,),
    )

    merch_row = _fetchone(
        "SELECT COUNT(*) as cnt FROM ambassador_events WHERE created_at >= ? AND merch_eligible=1",
        (month_start,),
    )

    ticket_stats = get_ticket_stats()

    if _using_postgres:
        resolved_row = _fetchone(
            """SELECT AVG(
                EXTRACT(EPOCH FROM (updated_at::timestamp - created_at::timestamp)) / 3600
               ) as avg_hours
               FROM escalation_tickets WHERE status='RESOLVED' AND created_at >= ?""",
            (month_start,),
        )
    else:
        resolved_row = _fetchone(
            """SELECT AVG(
                (julianday(updated_at) - julianday(created_at)) * 24
               ) as avg_hours
               FROM escalation_tickets WHERE status='RESOLVED' AND created_at >= ?""",
            (month_start,),
        )

    return {
        "total_events": event_row["cnt"] if event_row else 0,
        "total_participants": event_row["total_p"] if event_row else 0,
        "merch_events": merch_row["cnt"] if merch_row else 0,
        "tickets": ticket_stats,
        "avg_resolution_hours": round((resolved_row["avg_hours"] or 0) if resolved_row else 0, 1),
    }


def close_db() -> None:
    sqlite_conn: sqlite3.Connection | None = getattr(_local, "sqlite_conn", None)
    if sqlite_conn is not None:
        sqlite_conn.close()
        _local.sqlite_conn = None

    pg_conn = getattr(_local, "pg_conn", None)
    if pg_conn is not None:
        try:
            pg_conn.close()
        except Exception:
            pass
        _local.pg_conn = None
