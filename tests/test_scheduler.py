from __future__ import annotations

import os
from pathlib import Path

import pytest

os.environ.setdefault("DISCORD_BOT_TOKEN", "test-token")

from src.db import close_db, get_ticket_stats, init_db, record_event_submission, create_ticket


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


class TestSchedulerMetrics:
    def test_get_all_month_stats_empty(self) -> None:
        from src.scheduler import _get_all_month_stats
        stats = _get_all_month_stats()
        assert stats["total_events"] == 0
        assert stats["total_participants"] == 0
        assert stats["merch_events"] == 0
        assert stats["tickets"]["total"] == 0

    def test_stats_with_events(self) -> None:
        record_event_submission(
            ambassador_id=1, ambassador_name="A", event_name="E1",
            participant_count=350, reward_tier="Tier 300+", merch_eligible=True,
        )
        record_event_submission(
            ambassador_id=2, ambassador_name="B", event_name="E2",
            participant_count=100, reward_tier="Standard", merch_eligible=False,
        )
        from src.scheduler import _get_all_month_stats
        stats = _get_all_month_stats()
        assert stats["total_events"] == 2
        assert stats["total_participants"] == 450
        assert stats["merch_events"] == 1

    def test_stats_with_tickets(self) -> None:
        create_ticket(
            channel_id=1, message_id=1, author_id=1, author_name="A",
            category="TECH", urgency="P1", poc_name="sreesanth",
        )
        create_ticket(
            channel_id=2, message_id=2, author_id=2, author_name="B",
            category="OPS", urgency="P2", poc_name="sanskruti",
        )
        from src.scheduler import _get_all_month_stats
        stats = _get_all_month_stats()
        assert stats["tickets"]["PENDING"] == 2
        assert stats["tickets"]["total"] == 2


class TestCertificatePreview:
    def test_generates_valid_png(self) -> None:
        from src.cert_generator import generate_certificate_preview
        data = generate_certificate_preview(
            name="Aarav Patel",
            college_name="IIT Madras",
            event_name="CodeFiesta 2026",
            rank=1,
            date="2026-09-19",
        )
        assert isinstance(data, bytes)
        assert len(data) > 1000
        assert data[:8] == b"\x89PNG\r\n\x1a\n"

    def test_minimal_fields(self) -> None:
        from src.cert_generator import generate_certificate_preview
        data = generate_certificate_preview(name="Test User")
        assert isinstance(data, bytes)
        assert data[:4] == b"\x89PNG"

    def test_all_ranks(self) -> None:
        from src.cert_generator import generate_certificate_preview
        for rank in (1, 2, 3, 10, 100):
            data = generate_certificate_preview(name=f"Rank{rank}", rank=rank)
            assert len(data) > 500


class TestEventWindowQuery:
    def test_events_in_window(self) -> None:
        from src.scheduler import _get_events_in_window
        events = _get_events_in_window(-100, 100)
        assert isinstance(events, list)
