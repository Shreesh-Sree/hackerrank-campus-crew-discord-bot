from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from hrcc_bot.core import db as db_mod
from hrcc_bot.core.db import (
    _execute,
    _fetchall,
    close_db,
    create_ticket,
    init_db,
    log_audit,
    record_event_submission,
    save_conversation_turn,
    upsert_ambassador_profile,
)
from hrcc_bot.core.privacy import USER_DATA_COLUMNS, delete_user_data, export_user_data, purge_expired
from hrcc_bot.pipeline.context import memory


@pytest.fixture(autouse=True)
def _use_temp_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(db_mod, "_SQLITE_PATH", tmp_path / "test.db")
    monkeypatch.setattr(db_mod, "_using_postgres", False)
    db_mod._local.sqlite_conn = None  # type: ignore[attr-defined]
    init_db()
    yield
    close_db()


def _seed(user_id: int) -> None:
    create_ticket(channel_id=1, message_id=1, author_id=user_id, author_name="u",
                  category="OPS", urgency="P2", poc_name="sanskruti", description="issue")
    record_event_submission(ambassador_id=user_id, ambassador_name="u", event_name="E",
                            participant_count=10, reward_tier="Tier <300", merch_eligible=False, csv_sha256="x")
    upsert_ambassador_profile(ambassador_id=user_id, ambassador_name="u")
    save_conversation_turn(user_id, "user", "hello")
    log_audit(actor_id=user_id, actor_name="u-name", action="TEST")


class TestExportAndDelete:
    def test_export_contains_only_that_user(self) -> None:
        _seed(1)
        _seed(2)
        data = export_user_data(1)
        assert {"escalation_tickets", "ambassador_events", "ambassador_profiles", "conversation_turns", "audit_log"} <= set(data)
        assert all(row["author_id"] == 1 for row in data["escalation_tickets"])

    def test_export_empty_for_unknown_user(self) -> None:
        assert export_user_data(404) == {}

    def test_delete_removes_rows_and_anonymises_audit(self) -> None:
        _seed(1)
        _seed(2)
        memory.add_user_message(1, "cached")

        counts = delete_user_data(1)

        assert counts["escalation_tickets"] == 1
        assert counts["conversation_turns"] == 2  # seeded turn + the cached one (memory persists to DB)
        remaining = export_user_data(1)
        assert set(remaining) == {"audit_log"}
        assert all(r["actor_name"] == "[deleted]" for r in remaining["audit_log"])
        assert memory.get_history(1) == []
        assert "escalation_tickets" in export_user_data(2)

    def test_every_user_table_is_covered(self) -> None:
        """New tables holding user ids must be added to USER_DATA_COLUMNS (or explicitly exempted)."""
        exempt = {"audit_log", "support_notices"}  # anonymised / staff-authored notices
        schema = db_mod._SQLITE_SCHEMA
        tables = set(re.findall(r"CREATE TABLE IF NOT EXISTS (\w+)", schema))
        covered = {t for t, _ in USER_DATA_COLUMNS}
        assert tables - covered - exempt == set()


class TestRetentionPurge:
    def _age(self, table: str, column: str, days: int) -> None:
        old = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        _execute(f"UPDATE {table} SET {column} = ?", (old,))

    def test_old_records_purged_recent_kept(self) -> None:
        _seed(1)
        self._age("escalation_tickets", "created_at", 400)
        create_ticket(channel_id=1, message_id=1, author_id=9, author_name="n",
                      category="OPS", urgency="P2", poc_name="sanskruti", description="new")

        counts = purge_expired(record_days=365, conversation_days=30)

        assert counts.get("escalation_tickets") == 1
        assert [t["author_id"] for t in _fetchall("SELECT author_id FROM escalation_tickets")] == [9]

    def test_conversations_use_shorter_window(self) -> None:
        save_conversation_turn(1, "user", "old")
        self._age("conversation_turns", "timestamp", 45)
        save_conversation_turn(1, "user", "new")

        purge_expired(record_days=365, conversation_days=30)

        assert [r["content"] for r in _fetchall("SELECT content FROM conversation_turns")] == ["new"]

    def test_nothing_to_purge(self) -> None:
        _seed(1)
        assert purge_expired(record_days=365, conversation_days=30) == {}
