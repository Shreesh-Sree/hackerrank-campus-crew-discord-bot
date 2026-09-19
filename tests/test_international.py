from __future__ import annotations

import os
from pathlib import Path

import pytest

os.environ.setdefault("DISCORD_BOT_TOKEN", "test-token")

from src.db import (
    REGIONS,
    award_points,
    close_db,
    create_collab_request,
    find_ambassadors_by_country,
    find_ambassadors_by_region,
    get_ambassador_points,
    get_ambassador_profile,
    get_college_leaderboard,
    get_country_leaderboard,
    get_global_leaderboard,
    get_open_collab_requests,
    get_region_leaderboard,
    init_db,
    resolve_region,
    update_collab_status,
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


class TestRegionMapping:
    def test_india_maps_to_apac(self) -> None:
        assert resolve_region("India") == "Asia-Pacific"

    def test_us_maps_to_americas(self) -> None:
        assert resolve_region("United States") == "Americas"

    def test_germany_maps_to_emea(self) -> None:
        assert resolve_region("Germany") == "EMEA"

    def test_brazil_maps_to_americas(self) -> None:
        assert resolve_region("Brazil") == "Americas"

    def test_nigeria_maps_to_emea(self) -> None:
        assert resolve_region("Nigeria") == "EMEA"

    def test_japan_maps_to_apac(self) -> None:
        assert resolve_region("Japan") == "Asia-Pacific"

    def test_unknown_country_maps_to_other(self) -> None:
        assert resolve_region("Atlantis") == "Other"

    def test_all_regions_have_countries(self) -> None:
        for region_name, countries in REGIONS.items():
            assert len(countries) > 0, f"{region_name} has no countries"
            for c in countries:
                assert resolve_region(c) == region_name


class TestGeographicProfiles:
    def test_profile_stores_geography(self) -> None:
        p = upsert_ambassador_profile(
            ambassador_id=1, ambassador_name="Alice",
            college_name="MIT", country="United States", region="Americas", timezone_str="US/Eastern",
        )
        assert p["country"] == "United States"
        assert p["region"] == "Americas"
        assert p["timezone_str"] == "US/Eastern"

    def test_update_preserves_geography(self) -> None:
        upsert_ambassador_profile(
            ambassador_id=2, ambassador_name="Bob",
            college_name="IIT", country="India", region="Asia-Pacific",
        )
        p = upsert_ambassador_profile(
            ambassador_id=2, ambassador_name="Bob Updated", current_stage="LIVE",
        )
        assert p["country"] == "India"
        assert p["region"] == "Asia-Pacific"
        assert p["ambassador_name"] == "Bob Updated"

    def test_points_inherit_geography_from_profile(self) -> None:
        upsert_ambassador_profile(
            ambassador_id=3, ambassador_name="Charlie",
            country="Brazil", region="Americas",
        )
        pts = award_points(
            ambassador_id=3, ambassador_name="Charlie",
            points_delta=100, action_type="CONTEST_HOSTED",
        )
        assert pts["country"] == "Brazil"
        assert pts["region"] == "Americas"


class TestGeographicLeaderboards:
    def _seed(self) -> None:
        data = [
            (10, "Alice", "MIT", "United States", "Americas", 500),
            (11, "Bob", "IIT Madras", "India", "Asia-Pacific", 800),
            (12, "Carlos", "USP", "Brazil", "Americas", 300),
            (13, "Diana", "TU Munich", "Germany", "EMEA", 600),
            (14, "Emi", "U Tokyo", "Japan", "Asia-Pacific", 400),
            (15, "Fatima", "KFUPM", "Saudi Arabia", "EMEA", 200),
            (16, "George", "U Toronto", "Canada", "Americas", 700),
        ]
        for aid, name, college, country, region, pts in data:
            upsert_ambassador_profile(
                ambassador_id=aid, ambassador_name=name,
                college_name=college, country=country, region=region,
            )
            award_points(
                ambassador_id=aid, ambassador_name=name,
                college_name=college, country=country, region=region,
                points_delta=pts, action_type="CONTEST_HOSTED",
            )

    def test_global_leaderboard_sorted(self) -> None:
        self._seed()
        lb = get_global_leaderboard(limit=10)
        assert len(lb) == 7
        assert lb[0]["ambassador_name"] == "Bob"
        assert lb[0]["total_points"] == 800

    def test_region_leaderboard_americas(self) -> None:
        self._seed()
        lb = get_region_leaderboard("Americas", limit=10)
        assert len(lb) == 3
        assert lb[0]["ambassador_name"] == "George"

    def test_region_leaderboard_apac(self) -> None:
        self._seed()
        lb = get_region_leaderboard("Asia-Pacific", limit=10)
        assert len(lb) == 2
        assert lb[0]["ambassador_name"] == "Bob"

    def test_region_leaderboard_emea(self) -> None:
        self._seed()
        lb = get_region_leaderboard("EMEA", limit=10)
        assert len(lb) == 2
        assert lb[0]["ambassador_name"] == "Diana"

    def test_country_leaderboard(self) -> None:
        self._seed()
        lb = get_country_leaderboard("India", limit=10)
        assert len(lb) == 1
        assert lb[0]["ambassador_name"] == "Bob"

    def test_country_leaderboard_empty(self) -> None:
        self._seed()
        lb = get_country_leaderboard("Antarctica", limit=10)
        assert lb == []

    def test_college_leaderboard_still_works(self) -> None:
        self._seed()
        lb = get_college_leaderboard("MIT", limit=10)
        assert len(lb) == 1


class TestAmbassadorDiscovery:
    def _seed(self) -> None:
        for i, (name, country, region) in enumerate([
            ("Alice", "India", "Asia-Pacific"),
            ("Bob", "India", "Asia-Pacific"),
            ("Carlos", "Brazil", "Americas"),
            ("Diana", "Germany", "EMEA"),
        ], start=100):
            upsert_ambassador_profile(
                ambassador_id=i, ambassador_name=name,
                country=country, region=region,
            )

    def test_find_by_country(self) -> None:
        self._seed()
        results = find_ambassadors_by_country("India")
        assert len(results) == 2

    def test_find_by_region(self) -> None:
        self._seed()
        results = find_ambassadors_by_region("Asia-Pacific")
        assert len(results) == 2

    def test_find_empty_country(self) -> None:
        self._seed()
        assert find_ambassadors_by_country("Antarctica") == []


class TestCollabRequests:
    def test_create_and_browse(self) -> None:
        req = create_collab_request(
            requester_id=1, requester_name="Alice",
            event_name="Global Hackathon", event_format="hackathon",
            proposed_date="15 November 2026", target_country="India",
            message="Looking for a partner in India!",
        )
        assert req["status"] == "OPEN"
        assert req["event_name"] == "Global Hackathon"

        open_reqs = get_open_collab_requests(10)
        assert len(open_reqs) == 1

    def test_accept_collab(self) -> None:
        req = create_collab_request(
            requester_id=2, requester_name="Bob",
            event_name="Joint Contest", target_country="any",
        )
        updated = update_collab_status(req["id"], "ACCEPTED")
        assert updated is not None
        assert updated["status"] == "ACCEPTED"

        open_reqs = get_open_collab_requests(10)
        assert len(open_reqs) == 0

    def test_multiple_collab_requests(self) -> None:
        for i in range(5):
            create_collab_request(
                requester_id=i + 10, requester_name=f"User{i}",
                event_name=f"Event {i}", target_country="any",
            )
        assert len(get_open_collab_requests(10)) == 5
