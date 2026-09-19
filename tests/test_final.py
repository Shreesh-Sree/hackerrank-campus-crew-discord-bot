from __future__ import annotations

import os
import re
from pathlib import Path

import pytest

os.environ.setdefault("DISCORD_BOT_TOKEN", "test-token")

from src.db import close_db, create_ticket, init_db
from src.incident_cluster import IncidentClusterEngine
from src.rubrics import scrub_secrets


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


class TestIncidentClustering:
    def test_no_cluster_below_threshold(self) -> None:
        engine = IncidentClusterEngine(threshold=3)
        r1 = engine.ingest("HRW not working", author_id=1, channel_id=10)
        r2 = engine.ingest("HRW not working for me", author_id=2, channel_id=10)
        assert r1 is None
        assert r2 is None

    def test_cluster_triggers_at_threshold(self) -> None:
        engine = IncidentClusterEngine(threshold=3)
        engine.ingest("getting 500 error on HRW", author_id=1, channel_id=10)
        engine.ingest("500 error status on test page", author_id=2, channel_id=11)
        r = engine.ingest("HRW shows 500 error", author_id=3, channel_id=12)
        assert r is not None
        assert r.count == 3

    def test_same_user_doesnt_inflate_count(self) -> None:
        engine = IncidentClusterEngine(threshold=3)
        engine.ingest("HRW not opening", author_id=1, channel_id=10)
        engine.ingest("HRW still not opening", author_id=1, channel_id=10)
        r = engine.ingest("HRW is not opening again", author_id=1, channel_id=10)
        assert r is None

    def test_subsequent_reports_suppressed(self) -> None:
        engine = IncidentClusterEngine(threshold=3)
        for i in range(5):
            r = engine.ingest(f"500 error status on hrw", author_id=i, channel_id=10)
        assert r is not None
        assert r.count == 5

    def test_non_error_messages_ignored(self) -> None:
        engine = IncidentClusterEngine(threshold=3)
        r = engine.ingest("How do I create a contest?", author_id=1, channel_id=10)
        assert r is None

    def test_resolve_clears_incident(self) -> None:
        engine = IncidentClusterEngine(threshold=2)
        engine.ingest("platform down and not loading", author_id=1, channel_id=10)
        engine.ingest("platform is down right now", author_id=2, channel_id=11)
        active = engine.get_active_incidents()
        assert len(active) >= 1
        for inc in active:
            engine.resolve(inc.signature)
        assert len(engine.get_active_incidents()) == 0

    def test_multiple_different_signatures(self) -> None:
        engine = IncidentClusterEngine(threshold=2)
        engine.ingest("500 error status on page", author_id=1, channel_id=10)
        engine.ingest("500 error status persists", author_id=2, channel_id=10)
        engine.ingest("cannot login to platform", author_id=3, channel_id=11)
        engine.ingest("unable to login to HRW", author_id=4, channel_id=11)
        active = engine.get_active_incidents()
        assert len(active) == 2


class TestDiscordTokenScrubbing:
    def test_discord_bot_token_scrubbed(self) -> None:
        # Synthetic token matching Discord format: base64id.timestamp.hmac
        token = "MXXXXXXXXXXXXXXXXXXXXXXXX.XXXXXX.XXXXXXXXXXXXXXXXXXXXXXXXXXX"
        text = f"The token is {token} for the bot"
        scrubbed = scrub_secrets(text)
        assert token not in scrubbed
        assert "[REDACTED]" in scrubbed

    def test_normal_text_not_scrubbed(self) -> None:
        text = "How do I set up a coding contest on HRW?"
        assert scrub_secrets(text) == text

    def test_ip_addresses_scrubbed(self) -> None:
        text = "Server at 10.1.53.27 and 127.0.0.1"
        scrubbed = scrub_secrets(text)
        assert "10.1.53.27" not in scrubbed
        assert "127.0.0.1" not in scrubbed


class TestXlsxParsing:
    def test_xlsx_creates_workbook(self) -> None:
        import openpyxl
        import io
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.append(["Name", "Score"])
        ws.append(["Alice", 300])
        ws.append(["Bob", 0])
        buf = io.BytesIO()
        wb.save(buf)
        xlsx_bytes = buf.getvalue()

        from src.csv_validator import parse_contest_csv
        result = parse_contest_csv(xlsx_bytes, event_name="Excel Test", filename="test.xlsx")
        assert result.active_participants == 1
        assert result.winners[0]["name"] == "Alice"

    def test_xlsx_without_filename_hint(self) -> None:
        import openpyxl
        import io
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.append(["Name", "Score"])
        ws.append(["Charlie", 500])
        buf = io.BytesIO()
        wb.save(buf)

        from src.csv_validator import parse_contest_csv
        result = parse_contest_csv(buf.getvalue(), event_name="NoHint")
        assert result.active_participants >= 1


class TestEscalateCommand:
    def test_urgency_classification_from_escalation(self) -> None:
        from src.escalation import _classify_urgency
        assert _classify_urgency("Contest is live and test link broken") == "P0"
        assert _classify_urgency("My welcome kit hasn't arrived") == "P2"
        assert _classify_urgency("HRW invitation pending for 3 days") == "P1"


class TestEventCheckLogic:
    def test_chakra_in_url(self) -> None:
        url = "https://hackerrank.com/work/chakra/assessment"
        assert "chakra" in url.lower()

    def test_skillup_in_url(self) -> None:
        url = "https://hackerrank.com/skillup/python"
        assert "skillup" in url.lower()

    def test_hrw_url_detected(self) -> None:
        url = "https://hackerrank.com/work/tests/12345"
        assert "hackerrank.com/work" in url.lower()

    def test_hrc_url_detected(self) -> None:
        url = "https://hackerrank.com/contests/my-contest"
        assert "hackerrank.com" in url.lower()
