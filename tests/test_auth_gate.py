from __future__ import annotations

import os
from pathlib import Path

import pytest

os.environ.setdefault("DISCORD_BOT_TOKEN", "test-token")

from src.auth_gate import (
    PRIVACY_EPHEMERAL,
    Role,
    UNGATED_COMMANDS,
    check_gate,
    get_user_role,
    is_ephemeral_command,
)
from src.db import (
    add_moderator,
    close_db,
    create_hrw_link,
    get_all_ambassadors_export,
    get_all_tickets,
    get_hrw_link,
    init_db,
    is_moderator,
    remove_moderator,
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


class TestRoleResolution:
    def test_unregistered_user(self) -> None:
        assert get_user_role(99999) == Role.UNREGISTERED

    def test_registered_ambassador(self) -> None:
        create_hrw_link(discord_id=100, hrw_user_id="hrw_100", hrw_email="amb@test.com", hrw_name="Amb")
        assert get_user_role(100) == Role.AMBASSADOR

    def test_moderator_role(self) -> None:
        create_hrw_link(discord_id=200, hrw_user_id="hrw_200", hrw_email="mod@test.com", hrw_name="Mod")
        add_moderator(200, 0)
        assert get_user_role(200) == Role.MODERATOR

    def test_admin_role(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from src import config
        monkeypatch.setattr(config.settings, "poc_discord_sreesanth", "300")
        assert get_user_role(300) == Role.ADMIN

    def test_owner_role(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from src import config
        monkeypatch.setattr(config.settings, "owner_discord_id", "400")
        assert get_user_role(400) == Role.OWNER

    def test_role_hierarchy(self) -> None:
        assert Role.OWNER > Role.ADMIN > Role.MODERATOR > Role.AMBASSADOR > Role.UNREGISTERED


class TestGateCheck:
    def test_ungated_commands_always_pass(self) -> None:
        for cmd in UNGATED_COMMANDS:
            assert check_gate(99999, cmd) is None

    def test_gated_command_blocks_unregistered(self) -> None:
        result = check_gate(99999, "my_tests")
        assert result is not None
        assert "register" in result.lower()

    def test_gated_command_passes_for_registered(self) -> None:
        create_hrw_link(discord_id=500, hrw_user_id="hrw_500", hrw_email="a@b.com")
        assert check_gate(500, "my_tests") is None

    def test_gate_blocks_my_status(self) -> None:
        assert check_gate(99999, "my_status") is not None

    def test_gate_blocks_escalate(self) -> None:
        assert check_gate(99999, "escalate") is not None


class TestHRWLinks:
    def test_create_and_get(self) -> None:
        link = create_hrw_link(discord_id=600, hrw_user_id="hrw_600", hrw_email="test@hrw.com", hrw_name="Test User")
        assert link["hrw_user_id"] == "hrw_600"
        assert link["hrw_email"] == "test@hrw.com"

        fetched = get_hrw_link(600)
        assert fetched is not None
        assert fetched["hrw_name"] == "Test User"

    def test_upsert_updates(self) -> None:
        create_hrw_link(discord_id=601, hrw_user_id="old", hrw_email="old@test.com")
        create_hrw_link(discord_id=601, hrw_user_id="new", hrw_email="new@test.com", hrw_name="Updated")
        link = get_hrw_link(601)
        assert link is not None
        assert link["hrw_user_id"] == "new"
        assert link["hrw_email"] == "new@test.com"

    def test_nonexistent_returns_none(self) -> None:
        assert get_hrw_link(99999) is None


class TestModerators:
    def test_add_and_check(self) -> None:
        assert not is_moderator(700)
        add_moderator(700, 0)
        assert is_moderator(700)

    def test_remove(self) -> None:
        add_moderator(701, 0)
        assert is_moderator(701)
        remove_moderator(701)
        assert not is_moderator(701)

    def test_double_add_no_error(self) -> None:
        add_moderator(702, 0)
        add_moderator(702, 0)
        assert is_moderator(702)


class TestPrivacyClassification:
    def test_ephemeral_commands(self) -> None:
        assert is_ephemeral_command("my_status")
        assert is_ephemeral_command("my_tests")
        assert is_ephemeral_command("register")
        assert is_ephemeral_command("admin_stats")
        assert is_ephemeral_command("escalate")

    def test_public_commands_not_ephemeral(self) -> None:
        assert not is_ephemeral_command("rules")
        assert not is_ephemeral_command("sop")
        assert not is_ephemeral_command("leaderboard")
        assert not is_ephemeral_command("marketing")


class TestAdminExport:
    def test_empty_export(self) -> None:
        rows = get_all_ambassadors_export()
        assert rows == []

    def test_export_with_data(self) -> None:
        from src.db import upsert_ambassador_profile, award_points
        upsert_ambassador_profile(ambassador_id=800, ambassador_name="ExportTest", college_name="MIT", country="US")
        create_hrw_link(discord_id=800, hrw_user_id="hrw_800", hrw_email="export@test.com")
        award_points(ambassador_id=800, ambassador_name="ExportTest", points_delta=100, action_type="CONTEST_HOSTED")

        rows = get_all_ambassadors_export()
        assert len(rows) == 1
        assert rows[0]["ambassador_name"] == "ExportTest"
        assert rows[0]["hrw_email"] == "export@test.com"
        assert rows[0]["total_points"] == 100


class TestAllTickets:
    def test_empty(self) -> None:
        assert get_all_tickets() == []

    def test_returns_tickets(self) -> None:
        from src.db import create_ticket
        create_ticket(channel_id=1, message_id=1, author_id=1, author_name="A",
                       category="TECH", urgency="P1", poc_name="sreesanth")
        tickets = get_all_tickets()
        assert len(tickets) == 1
