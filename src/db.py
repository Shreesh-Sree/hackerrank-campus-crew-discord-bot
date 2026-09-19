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
        conn = _get_pg_conn()
        for table, col, typedef in _SQLITE_MIGRATIONS:
            pg_type = typedef.replace("TEXT", "TEXT").replace("INTEGER", "BIGINT")
            try:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {pg_type}")
                conn.commit()
                log.info("Migration: added %s.%s", table, col)
            except Exception:
                conn.rollback()
    else:
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
