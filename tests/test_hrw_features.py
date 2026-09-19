from __future__ import annotations

import os
from pathlib import Path

import pytest

os.environ.setdefault("DISCORD_BOT_TOKEN", "test-token")

from src.db import (
    close_db,
    create_showcase,
    get_recent_showcases,
    get_upcoming_events_calendar,
    init_db,
    record_event_submission,
    upsert_ambassador_profile,
    get_ambassador_events,
    get_ambassador_points,
    award_points,
    get_global_leaderboard,
    get_monthly_stats,
    TIER_BADGES,
    ACHIEVEMENT_DEFS,
    get_ambassador_achievements,
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


class TestShowcase:
    def test_create_and_get(self) -> None:
        create_showcase(
            ambassador_id=1, ambassador_name="Alice",
            event_name="CodeStorm", country="India",
            participant_count=300, highlight="Amazing turnout!",
            top_winner="Bob",
        )
        showcases = get_recent_showcases(limit=10)
        assert len(showcases) == 1
        assert showcases[0]["event_name"] == "CodeStorm"
        assert showcases[0]["country"] == "India"
        assert showcases[0]["participant_count"] == 300

    def test_multiple_showcases_sorted(self) -> None:
        for i in range(5):
            create_showcase(
                ambassador_id=i, ambassador_name=f"User{i}",
                event_name=f"Event{i}", participant_count=100 + i * 50,
            )
        showcases = get_recent_showcases(limit=10)
        assert len(showcases) == 5
        assert showcases[0]["event_name"] == "Event4"

    def test_empty_showcase(self) -> None:
        assert get_recent_showcases() == []


class TestCalendar:
    def test_empty_calendar(self) -> None:
        assert get_upcoming_events_calendar() == []

    def test_future_events_shown(self) -> None:
        record_event_submission(
            ambassador_id=10, ambassador_name="Alice",
            event_name="Future Event", event_date="2099-12-01",
            platform="HRW", participant_count=100,
        )
        events = get_upcoming_events_calendar()
        assert len(events) >= 1
        assert events[0]["event_name"] == "Future Event"


class TestImpactReport:
    def test_impact_data_available(self) -> None:
        upsert_ambassador_profile(
            ambassador_id=20, ambassador_name="TestAmb",
            college_name="MIT", country="United States",
        )
        record_event_submission(
            ambassador_id=20, ambassador_name="TestAmb",
            event_name="E1", participant_count=200,
        )
        record_event_submission(
            ambassador_id=20, ambassador_name="TestAmb",
            event_name="E2", participant_count=400, merch_eligible=True,
        )
        award_points(
            ambassador_id=20, ambassador_name="TestAmb",
            points_delta=250, action_type="CONTEST_HOSTED",
        )

        events = get_ambassador_events(20)
        pts = get_ambassador_points(20)

        assert len(events) == 2
        assert pts is not None
        assert pts["total_points"] == 250
        total_p = sum(e["participant_count"] for e in events)
        assert total_p == 600


class TestTrendsData:
    def test_trends_with_data(self) -> None:
        for i in range(5):
            upsert_ambassador_profile(
                ambassador_id=30 + i, ambassador_name=f"Amb{i}",
                country=["India", "US", "Brazil", "Germany", "Japan"][i],
                region=["Asia-Pacific", "Americas", "Americas", "EMEA", "Asia-Pacific"][i],
            )
            award_points(
                ambassador_id=30 + i, ambassador_name=f"Amb{i}",
                country=["India", "US", "Brazil", "Germany", "Japan"][i],
                region=["Asia-Pacific", "Americas", "Americas", "EMEA", "Asia-Pacific"][i],
                points_delta=100 * (i + 1), action_type="CONTEST_HOSTED",
            )

        lb = get_global_leaderboard(limit=1000)
        assert len(lb) == 5
        countries = set(a.get("country", "") for a in lb if a.get("country"))
        assert len(countries) == 5

    def test_monthly_stats_structure(self) -> None:
        stats = get_monthly_stats()
        assert "total_events" in stats
        assert "total_participants" in stats
        assert "tickets" in stats


class TestHRWApiModule:
    def test_base_url_set(self) -> None:
        from src.hrw_api import _BASE_URL
        assert "hackerrank.com" in _BASE_URL

    def test_headers_function(self) -> None:
        from src.hrw_api import _headers
        h = _headers()
        assert "Authorization" in h
