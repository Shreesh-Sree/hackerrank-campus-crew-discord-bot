"""User data export/deletion and retention purges promised in docs/legal/PRIVACY_POLICY.md."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from hrcc_bot.core.db import _execute, _fetchall, _fetchone

log = logging.getLogger("hrcc.privacy")

# (table, column holding the Discord user id) for every row that belongs to a user.
USER_DATA_COLUMNS: list[tuple[str, str]] = [
    ("escalation_tickets", "author_id"),
    ("ambassador_events", "ambassador_id"),
    ("ambassador_profiles", "ambassador_id"),
    ("ambassador_points", "ambassador_id"),
    ("points_ledger", "ambassador_id"),
    ("conversation_turns", "user_id"),
    ("collab_requests", "requester_id"),
    ("hrw_links", "discord_id"),
    ("moderators", "discord_id"),
    ("event_showcase", "ambassador_id"),
]

# The audit trail is kept for accountability, but names are anonymised on deletion.
_AUDIT_ANONYMISE = [
    ("actor_id", "actor_name"),
    ("target_id", "target_name"),
]

# (table, timestamp column) purged after the retention window.
RECORD_RETENTION: list[tuple[str, str]] = [
    ("escalation_tickets", "created_at"),
    ("ambassador_events", "created_at"),
]
CONVERSATION_RETENTION: tuple[str, str] = ("conversation_turns", "timestamp")


def _count(table: str, column: str, value: Any) -> int:
    row = _fetchone(f"SELECT COUNT(*) AS n FROM {table} WHERE {column} = ?", (value,))
    return int(row["n"]) if row else 0


def export_user_data(user_id: int) -> dict[str, list[dict[str, Any]]]:
    """Every row tied to ``user_id``, grouped by table (for access requests)."""
    data: dict[str, list[dict[str, Any]]] = {}
    for table, column in USER_DATA_COLUMNS:
        rows = _fetchall(f"SELECT * FROM {table} WHERE {column} = ?", (user_id,))
        if rows:
            data[table] = rows
    audit = _fetchall(
        "SELECT * FROM audit_log WHERE actor_id = ? OR target_id = ? ORDER BY created_at",
        (user_id, user_id),
    )
    if audit:
        data["audit_log"] = audit
    return data


def delete_user_data(user_id: int) -> dict[str, int]:
    """Delete a user's rows and anonymise their audit entries. Returns rows affected per table."""
    counts: dict[str, int] = {}
    for table, column in USER_DATA_COLUMNS:
        n = _count(table, column, user_id)
        if n:
            _execute(f"DELETE FROM {table} WHERE {column} = ?", (user_id,))
            counts[table] = n
    for id_col, name_col in _AUDIT_ANONYMISE:
        n = _count("audit_log", id_col, user_id)
        if n:
            _execute(f"UPDATE audit_log SET {name_col} = '[deleted]' WHERE {id_col} = ?", (user_id,))
            counts[f"audit_log ({name_col} anonymised)"] = n

    from hrcc_bot.pipeline.context import memory
    memory.clear(user_id)

    log.info("Deleted data for user %s: %s", user_id, counts)
    return counts


def purge_expired(record_days: int, conversation_days: int, now: datetime | None = None) -> dict[str, int]:
    """Delete tickets/events older than ``record_days`` and chat turns older than ``conversation_days``."""
    now = now or datetime.now(timezone.utc)
    plan = [(t, c, record_days) for t, c in RECORD_RETENTION]
    plan.append((*CONVERSATION_RETENTION, conversation_days))

    counts: dict[str, int] = {}
    for table, column, days in plan:
        cutoff = (now - timedelta(days=days)).isoformat()
        row = _fetchone(f"SELECT COUNT(*) AS n FROM {table} WHERE {column} < ?", (cutoff,))
        n = int(row["n"]) if row else 0
        if n:
            _execute(f"DELETE FROM {table} WHERE {column} < ?", (cutoff,))
            counts[table] = n
    if counts:
        log.info("Retention purge removed %s", counts)
    return counts
