from __future__ import annotations

import os
from pathlib import Path

import pytest

os.environ.setdefault("DISCORD_BOT_TOKEN", "test-token")

from src.db import (
    close_db,
    get_audit_log,
    get_audit_log_for_user,
    init_db,
    log_audit,
)


@pytest.fixture(autouse=True)
def _use_temp_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import src.db as db_mod

    test_db = tmp_path / "test.db"
    monkeypatch.setattr(db_mod, "_SQLITE_PATH", test_db)
    monkeypatch.setattr(db_mod, "_using_postgres", False)
    db_mod._local.sqlite_conn = None  # type: ignore[attr-defined]
    init_db()
    yield
    close_db()


class TestAuditLog:
    def test_log_and_retrieve(self) -> None:
        log_audit(actor_id=1, actor_name="Alice", action="REGISTER", details="HRW: alice@test.com")
        entries = get_audit_log(limit=10)
        assert len(entries) == 1
        assert entries[0]["action"] == "REGISTER"
        assert entries[0]["actor_name"] == "Alice"
        assert "alice@test.com" in entries[0]["details"]

    def test_multiple_entries_sorted(self) -> None:
        log_audit(actor_id=1, actor_name="Alice", action="REGISTER")
        log_audit(actor_id=2, actor_name="Bob", action="CSV_UPLOAD")
        log_audit(actor_id=3, actor_name="Charlie", action="ESCALATE")
        entries = get_audit_log(limit=10)
        assert len(entries) == 3
        assert entries[0]["actor_name"] == "Charlie"

    def test_limit_respected(self) -> None:
        for i in range(20):
            log_audit(actor_id=i, actor_name=f"User{i}", action="TEST")
        entries = get_audit_log(limit=5)
        assert len(entries) == 5

    def test_target_tracking(self) -> None:
        log_audit(
            actor_id=100, actor_name="Admin",
            action="GRANT_MOD", target_id=200, target_name="Ambassador",
        )
        entries = get_audit_log(limit=10)
        assert entries[0]["target_id"] == 200
        assert entries[0]["target_name"] == "Ambassador"

    def test_user_specific_log(self) -> None:
        log_audit(actor_id=1, actor_name="Alice", action="REGISTER")
        log_audit(actor_id=2, actor_name="Bob", action="CSV_UPLOAD")
        log_audit(actor_id=3, actor_name="Admin", action="GRANT_MOD", target_id=1, target_name="Alice")

        alice_log = get_audit_log_for_user(1, limit=10)
        assert len(alice_log) == 2

        bob_log = get_audit_log_for_user(2, limit=10)
        assert len(bob_log) == 1

    def test_empty_log(self) -> None:
        assert get_audit_log() == []

    def test_all_action_types_logged(self) -> None:
        actions = ["REGISTER", "CSV_UPLOAD", "ESCALATE", "ADMIN_POINTS", "GRANT_MOD", "REVOKE_MOD"]
        for i, action in enumerate(actions):
            log_audit(actor_id=i, actor_name=f"User{i}", action=action)
        entries = get_audit_log(limit=20)
        logged_actions = {e["action"] for e in entries}
        for action in actions:
            assert action in logged_actions
