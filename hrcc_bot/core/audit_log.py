from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from hrcc_bot.core.db import _fetchone, _execute, _ph, _p, init_db

log = logging.getLogger("hrcc.audit")


def get_audit_logs(
    actor_id: int | None = None,
    action: str | None = None,
    category: str | None = None,
    start_time: datetime | None = None,
    end_time: datetime | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """Query audit log with optional filters.

    Args:
        actor_id: Filter by ambassador/user ID
        action: Filter by action type (e.g., "CSV_UPLOAD", "EVENT_CREATED")
        category: Filter by category (OPS, TECH, DESIGN)
        start_time: Start of time range
        end_time: End of time range
        limit: Maximum results to return

    Returns:
        List of audit log entries as dicts
    """
    query = """
        SELECT
            id,
            actor_id,
            actor_name,
            action,
            category,
            urgency,
            description,
            created_at,
            updated_at
        FROM audit_logs
    """

    params: list[Any] = []

    if actor_id is not None:
        query += f" WHERE actor_id = {_ph(1)}"
        params.append(actor_id)

    if action is not None:
        query += f" AND action = {_ph(len(params) + 1)}"
        params.append(action)

    if category is not None:
        query += f" AND category = {_ph(len(params) + 1)}"
        params.append(category)

    if start_time is not None:
        query += f" AND created_at >= {_ph(len(params) + 1)}"
        params.append(start_time.isoformat())

    if end_time is not None:
        query += f" AND created_at <= {_ph(len(params) + 1)}"
        params.append(end_time.isoformat())

    query += f" ORDER BY created_at DESC LIMIT {limit}"

    try:
        conn = init_db()
        rows = conn.execute(query, _p(*params)).fetchall()
        return [dict(row) for row in rows]
    except Exception as e:
        log.error("Failed to query audit logs: %s", str(e))
        return []


def get_audit_log_summary(
    days: int = 30,
) -> dict[str, Any]:
    """Get summary statistics for audit logs.

    Args:
        days: Number of days to look back

    Returns:
        Dict with counts by action, category, and actor
    """
    cutoff = datetime.now(timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0
    ) - __import__("datetime").timedelta(days=days)

    query = """
        SELECT
            action,
            category,
            COUNT(*) as count,
            GROUP_CONCAT(DISTINCT actor_name) as actors
        FROM audit_logs
        WHERE created_at >= ?
        GROUP BY action, category
    """

    try:
        conn = init_db()
        rows = conn.execute(query, (cutoff.isoformat(),)).fetchall()

        summary: dict[str, dict[str, Any]] = {}
        for row in rows:
            key = f"{row['action']}|{row['category']}"
            if key not in summary:
                summary[key] = {
                    "action": row["action"],
                    "category": row["category"],
                    "count": int(row["count"]),
                    "actors": row["actors"].split(", ") if row["actors"] else [],
                }

        return {
            "days": days,
            "total_entries": sum(s["count"] for s in summary.values()),
            "entries": list(summary.values()),
        }
    except Exception as e:
        log.error("Failed to get audit log summary: %s", str(e))
        return {"days": days, "total_entries": 0, "entries": []}


def search_audit_logs(
    query_text: str,
    actor_id: int | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """Search audit logs by text content.

    Args:
        query_text: Text to search in description/actor_name
        actor_id: Optional filter by ID
        limit: Maximum results

    Returns:
        List of matching audit log entries
    """
    # Use LIKE for partial matches
    search_pattern = f"%{query_text}%"

    query = """
        SELECT
            id,
            actor_id,
            actor_name,
            action,
            category,
            urgency,
            description,
            created_at,
            updated_at
        FROM audit_logs
        WHERE (description LIKE ? OR actor_name LIKE ?)
    """

    params = [search_pattern, search_pattern]

    if actor_id is not None:
        query += f" AND actor_id = {_ph(len(params) + 1)}"
        params.append(actor_id)

    query += f" ORDER BY created_at DESC LIMIT {limit}"

    try:
        conn = init_db()
        rows = conn.execute(query, _p(*params)).fetchall()
        return [dict(row) for row in rows]
    except Exception as e:
        log.error("Failed to search audit logs: %s", str(e))
        return []


def get_ticket_audit_trail(
    ticket_code: str,
) -> list[dict[str, Any]]:
    """Get all audit entries for a specific ticket.

    Args:
        ticket_code: The ticket code (e.g., "HRCC-101")

    Returns:
        List of audit trail entries
    """
    query = """
        SELECT
            al.id,
            al.actor_id,
            al.actor_name,
            al.action,
            al.category,
            al.urgency,
            al.description,
            al.created_at,
            t.status as ticket_status,
            t.poc_name,
            t.created_at as ticket_created_at
        FROM audit_logs al
        LEFT JOIN tickets t ON al.ticket_code = t.ticket_code
        WHERE t.ticket_code = ?
        ORDER BY al.created_at ASC
    """

    try:
        conn = init_db()
        rows = conn.execute(query, (ticket_code,)).fetchall()
        return [dict(row) for row in rows]
    except Exception as e:
        log.error("Failed to get ticket audit trail: %s", str(e))
        return []


def export_audit_logs_to_csv(
    output_path: str,
    actor_id: int | None = None,
    action: str | None = None,
    category: str | None = None,
    start_time: datetime | None = None,
    end_time: datetime | None = None,
) -> bool:
    """Export filtered audit logs to CSV file.

    Args:
        output_path: Path for output CSV file
        actor_id: Optional filter by ID
        action: Optional filter by action
        category: Optional filter by category
        start_time: Start of time range
        end_time: End of time range

    Returns:
        True if export succeeded, False otherwise
    """
    try:
        logs = get_audit_logs(
            actor_id=actor_id,
            action=action,
            category=category,
            start_time=start_time,
            end_time=end_time,
            limit=10000,  # Export all matching entries
        )

        if not logs:
            return False

        import csv

        with open(output_path, "w", newline="", encoding="utf-8") as f:
            fieldnames = [
                "id",
                "actor_id",
                "actor_name",
                "action",
                "category",
                "urgency",
                "description",
                "created_at",
                "updated_at",
            ]
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(logs)

        log.info("Exported %d audit logs to %s", len(logs), output_path)
        return True

    except Exception as e:
        log.error("Failed to export audit logs: %s", str(e))
        return False


def get_audit_stats_by_actor(
    actor_id: int,
    days: int = 30,
) -> dict[str, Any]:
    """Get activity statistics for a specific actor.

    Args:
        actor_id: Ambassador/user ID
        days: Number of days to analyze

    Returns:
        Dict with action counts and timestamps
    """
    cutoff = datetime.now(timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0
    ) - __import__("datetime").timedelta(days=days)

    query = """
        SELECT
            action,
            COUNT(*) as count,
            MIN(created_at) as first_seen,
            MAX(created_at) as last_seen
        FROM audit_logs
        WHERE actor_id = ? AND created_at >= ?
        GROUP BY action
    """

    try:
        conn = init_db()
        rows = conn.execute(query, (actor_id, cutoff.isoformat())).fetchall()

        stats: dict[str, Any] = {
            "actor_id": actor_id,
            "days": days,
            "total_actions": sum(row["count"] for row in rows),
            "actions": {},
        }

        for row in rows:
            stats["actions"][row["action"]] = {
                "count": int(row["count"]),
                "first_seen": row["first_seen"],
                "last_seen": row["last_seen"],
            }

        return stats
    except Exception as e:
        log.error("Failed to get actor audit stats: %s", str(e))
        return {"actor_id": actor_id, "days": days, "total_actions": 0, "actions": {}}
