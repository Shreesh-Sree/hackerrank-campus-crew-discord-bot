from __future__ import annotations

import os
from pathlib import Path

import pytest

os.environ.setdefault("DISCORD_BOT_TOKEN", "test-token")

from src.db import (
    TIER_BADGES,
    award_points,
    close_db,
    get_ambassador_points,
    get_college_leaderboard,
    get_national_leaderboard,
    init_db,
)
from src.db import _compute_tier


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


class TestTierProgression:
    def test_apprentice_tier(self) -> None:
        assert _compute_tier(0) == "Apprentice Ambassador"
        assert _compute_tier(199) == "Apprentice Ambassador"

    def test_campus_lead_tier(self) -> None:
        assert _compute_tier(200) == "Campus Lead"
        assert _compute_tier(499) == "Campus Lead"

    def test_national_fellow_tier(self) -> None:
        assert _compute_tier(500) == "National Fellow"
        assert _compute_tier(999) == "National Fellow"

    def test_hall_of_fame_tier(self) -> None:
        assert _compute_tier(1000) == "Hall of Fame"
        assert _compute_tier(5000) == "Hall of Fame"

    def test_all_tiers_have_badges(self) -> None:
        for tier_name in ["Apprentice Ambassador", "Campus Lead", "National Fellow", "Hall of Fame"]:
            assert tier_name in TIER_BADGES


class TestPointsAwarding:
    def test_first_award_creates_record(self) -> None:
        result = award_points(
            ambassador_id=1, ambassador_name="Alice", college_name="MIT",
            points_delta=100, action_type="CONTEST_HOSTED", description="First contest",
        )
        assert result["total_points"] == 100
        assert result["tier_name"] == "Apprentice Ambassador"
        assert result["contests_hosted"] == 1

    def test_accumulates_points(self) -> None:
        award_points(ambassador_id=2, ambassador_name="Bob", points_delta=100, action_type="CONTEST_HOSTED")
        result = award_points(ambassador_id=2, ambassador_name="Bob", points_delta=150, action_type="PARTICIPANTS_300_PLUS")
        assert result["total_points"] == 250
        assert result["tier_name"] == "Campus Lead"
        assert result["merch_events_count"] == 1

    def test_tier_upgrades_automatically(self) -> None:
        for i in range(5):
            award_points(ambassador_id=3, ambassador_name="Charlie", points_delta=100, action_type="CONTEST_HOSTED")
        result = get_ambassador_points(3)
        assert result is not None
        assert result["total_points"] == 500
        assert result["tier_name"] == "National Fellow"

    def test_hall_of_fame(self) -> None:
        award_points(ambassador_id=4, ambassador_name="Diana", points_delta=1000, action_type="CONTEST_HOSTED")
        result = get_ambassador_points(4)
        assert result is not None
        assert result["tier_name"] == "Hall of Fame"

    def test_nonexistent_ambassador(self) -> None:
        assert get_ambassador_points(99999) is None


class TestLeaderboard:
    def _seed_ambassadors(self) -> None:
        data = [
            (10, "Alpha", "MIT", 500),
            (11, "Bravo", "MIT", 300),
            (12, "Charlie", "Stanford", 800),
            (13, "Delta", "Stanford", 100),
            (14, "Echo", "MIT", 1200),
        ]
        for aid, name, college, pts in data:
            award_points(ambassador_id=aid, ambassador_name=name, college_name=college,
                         points_delta=pts, action_type="CONTEST_HOSTED")

    def test_national_leaderboard_sorted(self) -> None:
        self._seed_ambassadors()
        lb = get_national_leaderboard(limit=10)
        assert len(lb) == 5
        assert lb[0]["ambassador_name"] == "Echo"
        assert lb[0]["total_points"] == 1200
        assert lb[1]["ambassador_name"] == "Charlie"

    def test_national_leaderboard_limit(self) -> None:
        self._seed_ambassadors()
        lb = get_national_leaderboard(limit=3)
        assert len(lb) == 3

    def test_college_leaderboard(self) -> None:
        self._seed_ambassadors()
        lb = get_college_leaderboard("MIT", limit=10)
        assert len(lb) == 3
        assert lb[0]["ambassador_name"] == "Echo"

    def test_empty_leaderboard(self) -> None:
        lb = get_national_leaderboard(limit=10)
        assert lb == []

    def test_college_leaderboard_empty(self) -> None:
        lb = get_college_leaderboard("Nonexistent University", limit=10)
        assert lb == []
