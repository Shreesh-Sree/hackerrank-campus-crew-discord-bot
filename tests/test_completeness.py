from __future__ import annotations

import os
from pathlib import Path

import pytest

os.environ.setdefault("DISCORD_BOT_TOKEN", "test-token")

from src.csv_validator import build_event_report, parse_contest_csv
from src.db import (
    ACHIEVEMENT_DEFS,
    award_points,
    check_and_grant_achievements,
    close_db,
    get_ambassador_achievements,
    get_inactive_ambassadors_this_month,
    grant_achievement,
    init_db,
    record_event_submission,
    upsert_ambassador_profile,
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


class TestAutoReport:
    def _make_csv(self, rows: list[list[str]]) -> bytes:
        return "\n".join(",".join(r) for r in rows).encode()

    def test_report_contains_event_info(self) -> None:
        csv = self._make_csv([
            ["Name", "Email", "Score"],
            ["Alice", "alice@example.com", "300"],
            ["Bob", "bob@example.com", "200"],
            ["Zero", "zero@example.com", "0"],
        ])
        result = parse_contest_csv(csv, event_name="CodeStorm 2026")
        report = build_event_report(result, ambassador_name="Siddharth")
        assert "CodeStorm 2026" in report
        assert "Siddharth" in report
        assert "Active Participants" in report
        assert "2" in report
        assert "Alice" in report
        assert "Sanskruti" in report

    def test_report_shows_completion_rate(self) -> None:
        csv = self._make_csv([
            ["Name", "Score"],
            ["A", "100"],
            ["B", "0"],
            ["C", "50"],
            ["D", "0"],
        ])
        result = parse_contest_csv(csv, event_name="Test")
        report = build_event_report(result)
        assert "50%" in report

    def test_report_shows_merch_eligibility(self) -> None:
        rows = [["Name", "Score"]] + [[f"S{i}", str(i + 1)] for i in range(350)]
        result = parse_contest_csv(self._make_csv(rows), event_name="Big Event")
        report = build_event_report(result)
        assert "Yes" in report
        assert "Tier 300+" in report


class TestAchievements:
    def test_all_achievements_defined(self) -> None:
        expected = ["first_event", "club_300", "five_streak", "collaborator",
                     "first_responder", "ten_events", "thousand_participants"]
        for key in expected:
            assert key in ACHIEVEMENT_DEFS
            assert "emoji" in ACHIEVEMENT_DEFS[key]
            assert "name" in ACHIEVEMENT_DEFS[key]

    def test_grant_achievement_once(self) -> None:
        assert grant_achievement(1, "first_event") is True
        assert grant_achievement(1, "first_event") is False

    def test_get_achievements(self) -> None:
        grant_achievement(2, "first_event")
        grant_achievement(2, "club_300")
        badges = get_ambassador_achievements(2)
        assert "first_event" in badges
        assert "club_300" in badges

    def test_auto_check_first_event(self) -> None:
        record_event_submission(
            ambassador_id=10, ambassador_name="Alice",
            event_name="Test", participant_count=100,
        )
        award_points(ambassador_id=10, ambassador_name="Alice",
                      points_delta=100, action_type="CONTEST_HOSTED")
        granted = check_and_grant_achievements(10)
        assert "first_event" in granted

    def test_auto_check_300_club(self) -> None:
        record_event_submission(
            ambassador_id=11, ambassador_name="Bob",
            event_name="Big", participant_count=400, merch_eligible=True,
        )
        award_points(ambassador_id=11, ambassador_name="Bob",
                      points_delta=250, action_type="PARTICIPANTS_300_PLUS")
        granted = check_and_grant_achievements(11)
        assert "first_event" in granted
        assert "club_300" in granted

    def test_auto_check_decathlon(self) -> None:
        for i in range(10):
            record_event_submission(
                ambassador_id=12, ambassador_name="Charlie",
                event_name=f"Event{i}", participant_count=50,
            )
            award_points(ambassador_id=12, ambassador_name="Charlie",
                          points_delta=100, action_type="CONTEST_HOSTED")
        granted = check_and_grant_achievements(12)
        assert "ten_events" in granted

    def test_unknown_achievement_ignored(self) -> None:
        assert grant_achievement(99, "nonexistent_badge") is False


class TestComplianceNudge:
    def test_inactive_returns_profiles_without_events(self) -> None:
        upsert_ambassador_profile(ambassador_id=100, ambassador_name="Inactive Alice")
        upsert_ambassador_profile(ambassador_id=101, ambassador_name="Inactive Bob")
        inactive = get_inactive_ambassadors_this_month()
        ids = {a["ambassador_id"] for a in inactive}
        assert 100 in ids
        assert 101 in ids

    def test_active_excluded_from_inactive(self) -> None:
        upsert_ambassador_profile(ambassador_id=200, ambassador_name="Active Charlie")
        record_event_submission(
            ambassador_id=200, ambassador_name="Active Charlie",
            event_name="Monthly Event", participant_count=100,
        )
        inactive = get_inactive_ambassadors_this_month()
        ids = {a["ambassador_id"] for a in inactive}
        assert 200 not in ids

    def test_empty_profiles_returns_empty(self) -> None:
        inactive = get_inactive_ambassadors_this_month()
        assert inactive == []


class TestDBMigrations:
    def test_migrations_run_without_error(self) -> None:
        from src.db import _apply_migrations
        _apply_migrations()
        _apply_migrations()
