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

    # Strict connect timeout — a dead/unreachable Postgres must fail fast
    # so the SQLite fallback can take over instead of stalling the bot.
    conn = psycopg.connect(
        settings.database_url,
        row_factory=dict_row,
        autocommit=False,
        connect_timeout=settings.pg_connect_timeout,
    )
    _local.pg_conn = conn
    return conn


def _pg_failover(exc: Exception) -> None:
    """Switch from PostgreSQL to the persistent SQLite store after a connection failure.

    Never raises — the Discord bot loop must survive database outages.
    """
    global _using_postgres

    log.warning(
        "[DB FAILOVER] PostgreSQL unreachable at %s. Falling back to persistent SQLite at %s (%s: %s)",
        settings.database_url.split("@")[-1],
        _SQLITE_PATH,
        type(exc).__name__,
        str(exc)[:200],
    )

    _using_postgres = False

    # Drop the broken thread-local Postgres connection.
    pg_conn = getattr(_local, "pg_conn", None)
    if pg_conn is not None:
        try:
            pg_conn.close()
        except Exception:
            pass
        _local.pg_conn = None

    # Make sure the SQLite schema exists before routing traffic to it.
    try:
        conn = _get_sqlite_conn()
        conn.executescript(_SQLITE_SCHEMA)
        conn.commit()
    except Exception:
        log.exception("[DB FAILOVER] Failed to initialize SQLite fallback store")


def _ph(n: int = 1) -> str:
    if _using_postgres:
        return ", ".join(["%s"] * n)
    return ", ".join(["?"] * n)


def _p(*args: Any) -> tuple[Any, ...]:
    return args


def _execute(sql: str, params: tuple = ()) -> None:
    if _using_postgres:
        try:
            conn = _get_pg_conn()
            conn.execute(sql.replace("?", "%s"), params)
            conn.commit()
            return
        except Exception as exc:
            _pg_failover(exc)

    # SQLite path (primary, or fallback after a Postgres drop).
    try:
        conn = _get_sqlite_conn()
        conn.execute(sql, params)
        conn.commit()
    except Exception:
        log.exception("SQLite write failed — statement dropped to protect the bot loop")


def _fetchone(sql: str, params: tuple = ()) -> dict[str, Any] | None:
    if _using_postgres:
        try:
            conn = _get_pg_conn()
            cur = conn.execute(sql.replace("?", "%s"), params)
            row = cur.fetchone()
            return dict(row) if row else None
        except Exception as exc:
            _pg_failover(exc)

    # SQLite path (primary, or fallback after a Postgres drop).
    try:
        conn = _get_sqlite_conn()
        row = conn.execute(sql, params).fetchone()
        return dict(row) if row else None
    except Exception:
        log.exception("SQLite read failed — returning no rows to protect the bot loop")
        return None


def _fetchall(sql: str, params: tuple = ()) -> list[dict[str, Any]]:
    if _using_postgres:
        try:
            conn = _get_pg_conn()
            cur = conn.execute(sql.replace("?", "%s"), params)
            return [dict(r) for r in cur.fetchall()]
        except Exception as exc:
            _pg_failover(exc)

    # SQLite path (primary, or fallback after a Postgres drop).
    try:
        conn = _get_sqlite_conn()
        rows = conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]
    except Exception:
        log.exception("SQLite read failed — returning no rows to protect the bot loop")
        return []


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
        country         TEXT    NOT NULL DEFAULT '',
        region          TEXT    NOT NULL DEFAULT '',
        timezone_str    TEXT    NOT NULL DEFAULT 'UTC',
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

    CREATE TABLE IF NOT EXISTS ambassador_points (
        ambassador_id   INTEGER PRIMARY KEY,
        ambassador_name TEXT    NOT NULL,
        college_name    TEXT    NOT NULL DEFAULT '',
        country         TEXT    NOT NULL DEFAULT '',
        region          TEXT    NOT NULL DEFAULT '',
        total_points    INTEGER NOT NULL DEFAULT 0,
        tier_name       TEXT    NOT NULL DEFAULT 'Apprentice Ambassador',
        contests_hosted INTEGER NOT NULL DEFAULT 0,
        merch_events_count INTEGER NOT NULL DEFAULT 0,
        updated_at      TEXT    NOT NULL
    );

    CREATE TABLE IF NOT EXISTS points_ledger (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        ambassador_id   INTEGER NOT NULL,
        points_delta    INTEGER NOT NULL,
        action_type     TEXT    NOT NULL,
        description     TEXT    NOT NULL DEFAULT '',
        created_at      TEXT    NOT NULL
    );

    CREATE TABLE IF NOT EXISTS collab_requests (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        requester_id    INTEGER NOT NULL,
        requester_name  TEXT    NOT NULL,
        target_id       INTEGER NOT NULL DEFAULT 0,
        target_country  TEXT    NOT NULL DEFAULT '',
        event_name      TEXT    NOT NULL,
        event_format    TEXT    NOT NULL DEFAULT '',
        proposed_date   TEXT    NOT NULL DEFAULT '',
        message         TEXT    NOT NULL DEFAULT '',
        status          TEXT    NOT NULL DEFAULT 'OPEN'
                        CHECK(status IN ('OPEN','ACCEPTED','DECLINED','COMPLETED')),
        created_at      TEXT    NOT NULL
    );

    CREATE INDEX IF NOT EXISTS idx_points_ambassador
        ON points_ledger(ambassador_id);
    CREATE INDEX IF NOT EXISTS idx_points_country
        ON ambassador_points(country);
    CREATE INDEX IF NOT EXISTS idx_points_region
        ON ambassador_points(region);
    CREATE INDEX IF NOT EXISTS idx_profiles_country
        ON ambassador_profiles(country);
    CREATE INDEX IF NOT EXISTS idx_collab_status
        ON collab_requests(status);

    CREATE TABLE IF NOT EXISTS hrw_links (
        discord_id      INTEGER PRIMARY KEY,
        hrw_user_id     TEXT    NOT NULL,
        hrw_email       TEXT    NOT NULL,
        hrw_name        TEXT    NOT NULL DEFAULT '',
        verified_at     TEXT    NOT NULL
    );

    CREATE TABLE IF NOT EXISTS moderators (
        discord_id      INTEGER PRIMARY KEY,
        granted_by      INTEGER NOT NULL,
        granted_at      TEXT    NOT NULL
    );

    CREATE TABLE IF NOT EXISTS event_showcase (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        ambassador_id   INTEGER NOT NULL,
        ambassador_name TEXT    NOT NULL,
        event_name      TEXT    NOT NULL,
        country         TEXT    NOT NULL DEFAULT '',
        participant_count INTEGER NOT NULL DEFAULT 0,
        highlight       TEXT    NOT NULL DEFAULT '',
        top_winner      TEXT    NOT NULL DEFAULT '',
        created_at      TEXT    NOT NULL
    );

    CREATE INDEX IF NOT EXISTS idx_showcase_created
        ON event_showcase(created_at);

    CREATE TABLE IF NOT EXISTS audit_log (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        actor_id        INTEGER NOT NULL,
        actor_name      TEXT    NOT NULL,
        action          TEXT    NOT NULL,
        target_id       INTEGER NOT NULL DEFAULT 0,
        target_name     TEXT    NOT NULL DEFAULT '',
        details         TEXT    NOT NULL DEFAULT '',
        created_at      TEXT    NOT NULL
    );

    CREATE INDEX IF NOT EXISTS idx_audit_created
        ON audit_log(created_at);
    CREATE INDEX IF NOT EXISTS idx_audit_actor
        ON audit_log(actor_id);
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
        country         TEXT    NOT NULL DEFAULT '',
        region          TEXT    NOT NULL DEFAULT '',
        timezone_str    TEXT    NOT NULL DEFAULT 'UTC',
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

    CREATE TABLE IF NOT EXISTS ambassador_points (
        ambassador_id   BIGINT PRIMARY KEY,
        ambassador_name TEXT    NOT NULL,
        college_name    TEXT    NOT NULL DEFAULT '',
        country         TEXT    NOT NULL DEFAULT '',
        region          TEXT    NOT NULL DEFAULT '',
        total_points    INTEGER NOT NULL DEFAULT 0,
        tier_name       TEXT    NOT NULL DEFAULT 'Apprentice Ambassador',
        contests_hosted INTEGER NOT NULL DEFAULT 0,
        merch_events_count INTEGER NOT NULL DEFAULT 0,
        updated_at      TEXT    NOT NULL
    );

    CREATE TABLE IF NOT EXISTS points_ledger (
        id              SERIAL PRIMARY KEY,
        ambassador_id   BIGINT  NOT NULL,
        points_delta    INTEGER NOT NULL,
        action_type     TEXT    NOT NULL,
        description     TEXT    NOT NULL DEFAULT '',
        created_at      TEXT    NOT NULL
    );

    CREATE TABLE IF NOT EXISTS collab_requests (
        id              SERIAL PRIMARY KEY,
        requester_id    BIGINT  NOT NULL,
        requester_name  TEXT    NOT NULL,
        target_id       BIGINT  NOT NULL DEFAULT 0,
        target_country  TEXT    NOT NULL DEFAULT '',
        event_name      TEXT    NOT NULL,
        event_format    TEXT    NOT NULL DEFAULT '',
        proposed_date   TEXT    NOT NULL DEFAULT '',
        message         TEXT    NOT NULL DEFAULT '',
        status          TEXT    NOT NULL DEFAULT 'OPEN'
                        CHECK(status IN ('OPEN','ACCEPTED','DECLINED','COMPLETED')),
        created_at      TEXT    NOT NULL
    );

    CREATE INDEX IF NOT EXISTS idx_points_ambassador
        ON points_ledger(ambassador_id);
    CREATE INDEX IF NOT EXISTS idx_points_country
        ON ambassador_points(country);
    CREATE INDEX IF NOT EXISTS idx_points_region
        ON ambassador_points(region);
    CREATE INDEX IF NOT EXISTS idx_profiles_country
        ON ambassador_profiles(country);
    CREATE INDEX IF NOT EXISTS idx_collab_status
        ON collab_requests(status);

    CREATE TABLE IF NOT EXISTS hrw_links (
        discord_id      BIGINT PRIMARY KEY,
        hrw_user_id     TEXT    NOT NULL,
        hrw_email       TEXT    NOT NULL,
        hrw_name        TEXT    NOT NULL DEFAULT '',
        verified_at     TEXT    NOT NULL
    );

    CREATE TABLE IF NOT EXISTS moderators (
        discord_id      BIGINT PRIMARY KEY,
        granted_by      BIGINT  NOT NULL,
        granted_at      TEXT    NOT NULL
    );

    CREATE TABLE IF NOT EXISTS event_showcase (
        id              SERIAL PRIMARY KEY,
        ambassador_id   BIGINT  NOT NULL,
        ambassador_name TEXT    NOT NULL,
        event_name      TEXT    NOT NULL,
        country         TEXT    NOT NULL DEFAULT '',
        participant_count INTEGER NOT NULL DEFAULT 0,
        highlight       TEXT    NOT NULL DEFAULT '',
        top_winner      TEXT    NOT NULL DEFAULT '',
        created_at      TEXT    NOT NULL
    );

    CREATE INDEX IF NOT EXISTS idx_showcase_created
        ON event_showcase(created_at);

    CREATE TABLE IF NOT EXISTS audit_log (
        id              SERIAL PRIMARY KEY,
        actor_id        BIGINT  NOT NULL,
        actor_name      TEXT    NOT NULL,
        action          TEXT    NOT NULL,
        target_id       BIGINT  NOT NULL DEFAULT 0,
        target_name     TEXT    NOT NULL DEFAULT '',
        details         TEXT    NOT NULL DEFAULT '',
        created_at      TEXT    NOT NULL
    );

    CREATE INDEX IF NOT EXISTS idx_audit_created
        ON audit_log(created_at);
    CREATE INDEX IF NOT EXISTS idx_audit_actor
        ON audit_log(actor_id);
"""


def init_db() -> None:
    global _using_postgres

    if _is_postgres():
        _using_postgres = True
        try:
            conn = _get_pg_conn()
            for stmt in _PG_SCHEMA.strip().split(";"):
                stmt = stmt.strip()
                if stmt:
                    conn.execute(stmt)
            conn.commit()
            log.info("PostgreSQL database initialized at %s", settings.database_url.split("@")[-1])
        except Exception as exc:
            # Connection refused, host unreachable, timeout — degrade to SQLite.
            _pg_failover(exc)

    if not _using_postgres:
        conn = _get_sqlite_conn()
        conn.executescript(_SQLITE_SCHEMA)
        conn.commit()
        log.info("SQLite database initialized at %s", _SQLITE_PATH)

    _apply_migrations()


_SQLITE_MIGRATIONS = [
    ("ambassador_profiles", "country", "TEXT NOT NULL DEFAULT ''"),
    ("ambassador_profiles", "region", "TEXT NOT NULL DEFAULT ''"),
    ("ambassador_profiles", "timezone_str", "TEXT NOT NULL DEFAULT 'UTC'"),
    ("ambassador_points", "country", "TEXT NOT NULL DEFAULT ''"),
    ("ambassador_points", "region", "TEXT NOT NULL DEFAULT ''"),
]


def _apply_migrations() -> None:
    if _using_postgres:
        try:
            conn = _get_pg_conn()
            for table, col, typedef in _SQLITE_MIGRATIONS:
                pg_type = typedef.replace("TEXT", "TEXT").replace("INTEGER", "BIGINT")
                try:
                    conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {pg_type}")
                    conn.commit()
                    log.info("Migration: added %s.%s", table, col)
                except Exception:
                    conn.rollback()
        except Exception as exc:
            _pg_failover(exc)

    if not _using_postgres:
        conn = _get_sqlite_conn()
        for table, col, typedef in _SQLITE_MIGRATIONS:
            try:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {typedef}")
                conn.commit()
                log.info("Migration: added %s.%s", table, col)
            except sqlite3.OperationalError:
                pass


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
    country: str = "",
    region: str = "",
    timezone_str: str = "",
    current_stage: str = "PLANNING",
    notes: str = "",
) -> dict[str, Any]:
    now = _now_iso()
    exc_kw = "EXCLUDED" if _using_postgres else "excluded"

    _execute(
        f"""INSERT INTO ambassador_profiles
            (ambassador_id, ambassador_name, college_name, country, region, timezone_str, current_stage, notes, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(ambassador_id) DO UPDATE SET
              ambassador_name={exc_kw}.ambassador_name,
              college_name=CASE WHEN {exc_kw}.college_name='' THEN ambassador_profiles.college_name ELSE {exc_kw}.college_name END,
              country=CASE WHEN {exc_kw}.country='' THEN ambassador_profiles.country ELSE {exc_kw}.country END,
              region=CASE WHEN {exc_kw}.region='' THEN ambassador_profiles.region ELSE {exc_kw}.region END,
              timezone_str=CASE WHEN {exc_kw}.timezone_str='' THEN ambassador_profiles.timezone_str ELSE {exc_kw}.timezone_str END,
              current_stage={exc_kw}.current_stage,
              notes=CASE WHEN {exc_kw}.notes='' THEN ambassador_profiles.notes ELSE {exc_kw}.notes END,
              updated_at={exc_kw}.updated_at""",
        (ambassador_id, ambassador_name, college_name, country, region,
         timezone_str or "UTC", current_stage, notes, now),
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


ACHIEVEMENT_DEFS: dict[str, dict[str, str | int]] = {
    "first_event": {"emoji": "🎯", "name": "First Event", "desc": "Hosted your first campus event"},
    "club_300": {"emoji": "🔥", "name": "300 Club", "desc": "Reached 300+ active participants"},
    "five_streak": {"emoji": "⚡", "name": "5-Month Streak", "desc": "Hosted events 5 months in a row"},
    "collaborator": {"emoji": "🤝", "name": "International Collaborator", "desc": "Completed a cross-country collab"},
    "first_responder": {"emoji": "🚨", "name": "P0 First Responder", "desc": "Triaged a P0 emergency ticket"},
    "ten_events": {"emoji": "🏅", "name": "Decathlon", "desc": "Hosted 10 contests"},
    "thousand_participants": {"emoji": "🌍", "name": "Global Impact", "desc": "Reached 1,000 total participants"},
}


def grant_achievement(ambassador_id: int, achievement_key: str) -> bool:
    existing = _fetchone(
        "SELECT 1 FROM points_ledger WHERE ambassador_id=? AND action_type=?",
        (ambassador_id, f"ACHIEVEMENT_{achievement_key.upper()}"),
    )
    if existing:
        return False

    defn = ACHIEVEMENT_DEFS.get(achievement_key)
    if not defn:
        return False

    _execute(
        "INSERT INTO points_ledger (ambassador_id, points_delta, action_type, description, created_at) "
        "VALUES (?, 0, ?, ?, ?)",
        (ambassador_id, f"ACHIEVEMENT_{achievement_key.upper()}", str(defn["name"]), _now_iso()),
    )
    return True


def get_ambassador_achievements(ambassador_id: int) -> list[str]:
    rows = _fetchall(
        "SELECT action_type FROM points_ledger WHERE ambassador_id=? AND action_type LIKE 'ACHIEVEMENT_%'",
        (ambassador_id,),
    )
    return [r["action_type"].replace("ACHIEVEMENT_", "").lower() for r in rows]


def check_and_grant_achievements(ambassador_id: int, ambassador_name: str = "") -> list[str]:
    granted: list[str] = []
    existing = set(get_ambassador_achievements(ambassador_id))

    pts = get_ambassador_points(ambassador_id)
    events = get_ambassador_events(ambassador_id)

    if events and "first_event" not in existing:
        if grant_achievement(ambassador_id, "first_event"):
            granted.append("first_event")

    if pts and pts["merch_events_count"] >= 1 and "club_300" not in existing:
        if grant_achievement(ambassador_id, "club_300"):
            granted.append("club_300")

    if pts and pts["contests_hosted"] >= 10 and "ten_events" not in existing:
        if grant_achievement(ambassador_id, "ten_events"):
            granted.append("ten_events")

    total_p = sum(e["participant_count"] for e in events) if events else 0
    if total_p >= 1000 and "thousand_participants" not in existing:
        if grant_achievement(ambassador_id, "thousand_participants"):
            granted.append("thousand_participants")

    # 5-month streak: check if events exist in 5 consecutive months
    if events and "five_streak" not in existing:
        from datetime import datetime
        months_with_events: set[str] = set()
        for e in events:
            created = e.get("created_at", "")
            if created:
                months_with_events.add(created[:7])  # "YYYY-MM"
        if len(months_with_events) >= 5:
            sorted_months = sorted(months_with_events, reverse=True)
            streak = 1
            for i in range(len(sorted_months) - 1):
                y1, m1 = int(sorted_months[i][:4]), int(sorted_months[i][5:7])
                y2, m2 = int(sorted_months[i + 1][:4]), int(sorted_months[i + 1][5:7])
                if (y1 * 12 + m1) - (y2 * 12 + m2) == 1:
                    streak += 1
                    if streak >= 5:
                        break
                else:
                    streak = 1
            if streak >= 5:
                if grant_achievement(ambassador_id, "five_streak"):
                    granted.append("five_streak")

    # International collaborator: completed a cross-country collab
    if "collaborator" not in existing:
        completed_collabs = _fetchall(
            "SELECT 1 FROM collab_requests WHERE (requester_id=? OR target_id=?) AND status='COMPLETED' LIMIT 1",
            (ambassador_id, ambassador_id),
        )
        if completed_collabs:
            if grant_achievement(ambassador_id, "collaborator"):
                granted.append("collaborator")

    # P0 first responder: acknowledged a P0 ticket
    if "first_responder" not in existing:
        p0_acks = _fetchall(
            "SELECT 1 FROM escalation_tickets WHERE urgency='P0' AND status IN ('ACKNOWLEDGED','RESOLVED') "
            "AND poc_id=? LIMIT 1",
            (str(ambassador_id),),
        )
        if p0_acks:
            if grant_achievement(ambassador_id, "first_responder"):
                granted.append("first_responder")

    return granted


TIER_THRESHOLDS = [
    (1000, "Hall of Fame"),
    (500, "National Fellow"),
    (200, "Campus Lead"),
    (0, "Apprentice Ambassador"),
]

TIER_BADGES = {
    "Apprentice Ambassador": "🎖️",
    "Campus Lead": "🥉",
    "National Fellow": "🥈",
    "Hall of Fame": "🥇",
}


def _compute_tier(points: int) -> str:
    for threshold, name in TIER_THRESHOLDS:
        if points >= threshold:
            return name
    return "Apprentice Ambassador"


def award_points(
    *,
    ambassador_id: int,
    ambassador_name: str,
    college_name: str = "",
    country: str = "",
    region: str = "",
    points_delta: int,
    action_type: str,
    description: str = "",
) -> dict[str, Any]:
    now = _now_iso()

    if not country or not region:
        profile = get_ambassador_profile(ambassador_id)
        if profile:
            country = country or profile.get("country", "")
            region = region or profile.get("region", "")

    _execute(
        "INSERT INTO points_ledger (ambassador_id, points_delta, action_type, description, created_at) "
        "VALUES (?, ?, ?, ?, ?)",
        (ambassador_id, points_delta, action_type, description, now),
    )

    existing = _fetchone("SELECT * FROM ambassador_points WHERE ambassador_id=?", (ambassador_id,))
    if existing:
        new_total = existing["total_points"] + points_delta
        new_contests = existing["contests_hosted"] + (1 if action_type == "CONTEST_HOSTED" else 0)
        new_merch = existing["merch_events_count"] + (1 if action_type == "PARTICIPANTS_300_PLUS" else 0)
        tier = _compute_tier(new_total)
        _execute(
            "UPDATE ambassador_points SET total_points=?, tier_name=?, contests_hosted=?, "
            "merch_events_count=?, country=CASE WHEN ?='' THEN country ELSE ? END, "
            "region=CASE WHEN ?='' THEN region ELSE ? END, "
            "updated_at=? WHERE ambassador_id=?",
            (new_total, tier, new_contests, new_merch,
             country, country, region, region, now, ambassador_id),
        )
    else:
        tier = _compute_tier(points_delta)
        _execute(
            "INSERT INTO ambassador_points (ambassador_id, ambassador_name, college_name, "
            "country, region, total_points, tier_name, contests_hosted, merch_events_count, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (ambassador_id, ambassador_name, college_name, country, region, points_delta, tier,
             1 if action_type == "CONTEST_HOSTED" else 0,
             1 if action_type == "PARTICIPANTS_300_PLUS" else 0, now),
        )

    return get_ambassador_points(ambassador_id) or {}


def get_ambassador_points(ambassador_id: int) -> dict[str, Any] | None:
    return _fetchone("SELECT * FROM ambassador_points WHERE ambassador_id=?", (ambassador_id,))


def get_global_leaderboard(limit: int = 10) -> list[dict[str, Any]]:
    return _fetchall(
        "SELECT * FROM ambassador_points ORDER BY total_points DESC LIMIT ?",
        (limit,),
    )


get_national_leaderboard = get_global_leaderboard


def get_region_leaderboard(region: str, limit: int = 10) -> list[dict[str, Any]]:
    return _fetchall(
        "SELECT * FROM ambassador_points WHERE region=? ORDER BY total_points DESC LIMIT ?",
        (region, limit),
    )


def get_country_leaderboard(country: str, limit: int = 10) -> list[dict[str, Any]]:
    return _fetchall(
        "SELECT * FROM ambassador_points WHERE country=? ORDER BY total_points DESC LIMIT ?",
        (country, limit),
    )


def get_inactive_ambassadors_this_month() -> list[dict[str, Any]]:
    now = datetime.now(timezone.utc)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0).isoformat()
    return _fetchall(
        """SELECT p.* FROM ambassador_profiles p
           WHERE NOT EXISTS (
             SELECT 1 FROM ambassador_events e
             WHERE e.ambassador_id = p.ambassador_id AND e.created_at >= ?
           )""",
        (month_start,),
    )


def find_ambassadors_by_country(country: str, limit: int = 20) -> list[dict[str, Any]]:
    return _fetchall(
        "SELECT * FROM ambassador_profiles WHERE country=? ORDER BY ambassador_name LIMIT ?",
        (country, limit),
    )


def find_ambassadors_by_region(region: str, limit: int = 20) -> list[dict[str, Any]]:
    return _fetchall(
        "SELECT * FROM ambassador_profiles WHERE region=? ORDER BY country, ambassador_name LIMIT ?",
        (region, limit),
    )


def create_collab_request(
    *,
    requester_id: int,
    requester_name: str,
    target_id: int = 0,
    target_country: str = "",
    event_name: str,
    event_format: str = "",
    proposed_date: str = "",
    message: str = "",
) -> dict[str, Any]:
    now = _now_iso()
    _execute(
        """INSERT INTO collab_requests
           (requester_id, requester_name, target_id, target_country,
            event_name, event_format, proposed_date, message, status, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'OPEN', ?)""",
        (requester_id, requester_name, target_id, target_country,
         event_name, event_format, proposed_date, message, now),
    )
    if _using_postgres:
        return _fetchone(
            "SELECT * FROM collab_requests WHERE requester_id=? AND created_at=?",
            (requester_id, now),
        ) or {}
    else:
        conn = _get_sqlite_conn()
        row_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        return _fetchone("SELECT * FROM collab_requests WHERE id=?", (row_id,)) or {}


def get_open_collab_requests(limit: int = 10) -> list[dict[str, Any]]:
    return _fetchall(
        "SELECT * FROM collab_requests WHERE status='OPEN' ORDER BY created_at DESC LIMIT ?",
        (limit,),
    )


def update_collab_status(request_id: int, status: str) -> dict[str, Any] | None:
    _execute("UPDATE collab_requests SET status=? WHERE id=?", (status, request_id))
    return _fetchone("SELECT * FROM collab_requests WHERE id=?", (request_id,))


REGIONS = {
    "Asia-Pacific": [
        "India", "Japan", "South Korea", "Singapore", "Malaysia", "Indonesia",
        "Philippines", "Thailand", "Vietnam", "Bangladesh", "Sri Lanka", "Nepal",
        "Pakistan", "Australia", "New Zealand", "China", "Taiwan", "Hong Kong",
    ],
    "EMEA": [
        "United Kingdom", "Germany", "France", "Netherlands", "Spain", "Italy",
        "Poland", "Sweden", "Norway", "Denmark", "Finland", "Ireland", "Belgium",
        "Switzerland", "Austria", "Portugal", "Czech Republic", "Romania", "Hungary",
        "Turkey", "Israel", "UAE", "Saudi Arabia", "Egypt", "Nigeria", "Kenya",
        "South Africa", "Ghana", "Morocco",
    ],
    "Americas": [
        "United States", "Canada", "Mexico", "Brazil", "Argentina", "Colombia",
        "Chile", "Peru", "Ecuador", "Venezuela", "Costa Rica", "Uruguay",
    ],
}

COUNTRY_TO_REGION: dict[str, str] = {}
for _region, _countries in REGIONS.items():
    for _c in _countries:
        COUNTRY_TO_REGION[_c] = _region


def resolve_region(country: str) -> str:
    return COUNTRY_TO_REGION.get(country, "Other")


def create_hrw_link(
    *, discord_id: int, hrw_user_id: str, hrw_email: str, hrw_name: str = "",
) -> dict[str, Any]:
    now = _now_iso()
    exc_kw = "EXCLUDED" if _using_postgres else "excluded"
    _execute(
        f"""INSERT INTO hrw_links (discord_id, hrw_user_id, hrw_email, hrw_name, verified_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(discord_id) DO UPDATE SET
              hrw_user_id={exc_kw}.hrw_user_id,
              hrw_email={exc_kw}.hrw_email,
              hrw_name={exc_kw}.hrw_name,
              verified_at={exc_kw}.verified_at""",
        (discord_id, hrw_user_id, hrw_email, hrw_name, now),
    )
    return get_hrw_link(discord_id) or {}


def get_hrw_link(discord_id: int) -> dict[str, Any] | None:
    return _fetchone("SELECT * FROM hrw_links WHERE discord_id=?", (discord_id,))


def add_moderator(discord_id: int, granted_by: int) -> None:
    now = _now_iso()
    _execute(
        "INSERT INTO moderators (discord_id, granted_by, granted_at) VALUES (?, ?, ?) "
        "ON CONFLICT(discord_id) DO NOTHING",
        (discord_id, granted_by, now),
    )


def remove_moderator(discord_id: int) -> None:
    _execute("DELETE FROM moderators WHERE discord_id=?", (discord_id,))


def is_moderator(discord_id: int) -> bool:
    row = _fetchone("SELECT 1 FROM moderators WHERE discord_id=?", (discord_id,))
    return row is not None


def get_all_tickets(limit: int = 20) -> list[dict[str, Any]]:
    return _fetchall(
        "SELECT * FROM escalation_tickets ORDER BY created_at DESC LIMIT ?", (limit,)
    )


def get_all_ambassadors_export() -> list[dict[str, Any]]:
    return _fetchall(
        """SELECT p.ambassador_id, p.ambassador_name, p.college_name, p.country, p.region,
                  p.timezone_str, p.current_stage,
                  COALESCE(pt.total_points, 0) as total_points,
                  COALESCE(pt.tier_name, 'Apprentice Ambassador') as tier_name,
                  COALESCE(pt.contests_hosted, 0) as contests_hosted,
                  h.hrw_email, h.hrw_user_id
           FROM ambassador_profiles p
           LEFT JOIN ambassador_points pt ON p.ambassador_id = pt.ambassador_id
           LEFT JOIN hrw_links h ON p.ambassador_id = h.discord_id
           ORDER BY COALESCE(pt.total_points, 0) DESC"""
    )


def create_showcase(
    *,
    ambassador_id: int,
    ambassador_name: str,
    event_name: str,
    country: str = "",
    participant_count: int = 0,
    highlight: str = "",
    top_winner: str = "",
) -> dict[str, Any]:
    now = _now_iso()
    _execute(
        """INSERT INTO event_showcase
           (ambassador_id, ambassador_name, event_name, country, participant_count,
            highlight, top_winner, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (ambassador_id, ambassador_name, event_name, country, participant_count,
         highlight, top_winner, now),
    )
    return {"ambassador_name": ambassador_name, "event_name": event_name, "created_at": now}


def get_recent_showcases(limit: int = 10) -> list[dict[str, Any]]:
    return _fetchall(
        "SELECT * FROM event_showcase ORDER BY created_at DESC LIMIT ?", (limit,)
    )


def get_upcoming_events_calendar() -> list[dict[str, Any]]:
    return _fetchall(
        """SELECT ambassador_name, event_name, event_date, platform
           FROM ambassador_events
           WHERE event_date != '' AND event_date >= date('now')
           ORDER BY event_date ASC LIMIT 15"""
    )


def log_audit(
    *,
    actor_id: int,
    actor_name: str,
    action: str,
    target_id: int = 0,
    target_name: str = "",
    details: str = "",
) -> None:
    _execute(
        """INSERT INTO audit_log (actor_id, actor_name, action, target_id, target_name, details, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (actor_id, actor_name, action, target_id, target_name, details, _now_iso()),
    )


def get_audit_log(limit: int = 50) -> list[dict[str, Any]]:
    return _fetchall(
        "SELECT * FROM audit_log ORDER BY created_at DESC LIMIT ?", (limit,)
    )


def get_audit_log_for_user(user_id: int, limit: int = 20) -> list[dict[str, Any]]:
    return _fetchall(
        "SELECT * FROM audit_log WHERE actor_id=? OR target_id=? ORDER BY created_at DESC LIMIT ?",
        (user_id, user_id, limit),
    )


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
