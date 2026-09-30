from __future__ import annotations

import os
import sqlite3
from pathlib import Path

import pytest

from hrcc_bot.config import settings
from hrcc_bot.core import db as db_mod
from hrcc_bot.core.health import DbMonitor, format_db_alert


@pytest.fixture()
def temp_sqlite(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "hrcc.db"
    monkeypatch.setattr(db_mod, "_SQLITE_PATH", path)
    monkeypatch.setattr(db_mod, "_using_postgres", False)
    db_mod._local.sqlite_conn = None  # type: ignore[attr-defined]
    yield path
    db_mod.close_db()


class TestFailoverMarker:
    def test_failover_writes_marker(self, temp_sqlite: Path) -> None:
        assert db_mod.failover_pending_since() is None
        db_mod._pg_failover(ConnectionError("refused"))
        assert db_mod.failover_pending_since() is not None

    def test_marker_keeps_original_timestamp(self, temp_sqlite: Path) -> None:
        db_mod._pg_failover(ConnectionError("x"))
        first = db_mod.failover_pending_since()
        db_mod._pg_failover(ConnectionError("y"))
        assert db_mod.failover_pending_since() == first

    def test_init_stays_on_sqlite_while_marker_present(self, temp_sqlite: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(settings, "database_url", "postgresql://u:p@127.0.0.1:1/none")
        db_mod._failover_marker().write_text("2026-01-01T00:00:00+00:00")
        called: list[bool] = []
        monkeypatch.setattr(db_mod, "_get_pg_conn", lambda: called.append(True))

        db_mod.init_db()

        assert db_mod._using_postgres is False
        assert called == []  # never even tried Postgres
        assert db_mod.db_status() == {
            "configured_postgres": True, "active": "sqlite", "failover_since": "2026-01-01T00:00:00+00:00",
        }

    def test_clear_marker(self, temp_sqlite: Path) -> None:
        db_mod._pg_failover(ConnectionError("x"))
        db_mod.clear_failover_marker()
        assert db_mod.failover_pending_since() is None


class TestDbMonitor:
    def test_failover_alerts_once(self) -> None:
        mon = DbMonitor()
        args = dict(configured_postgres=True, active="sqlite", postgres_reachable=False)
        assert mon.evaluate(**args) == "failover"
        assert mon.evaluate(**args) is None

    def test_postgres_back_alerts(self) -> None:
        mon = DbMonitor()
        mon.evaluate(configured_postgres=True, active="sqlite", postgres_reachable=False)
        assert mon.evaluate(configured_postgres=True, active="sqlite", postgres_reachable=True) == "postgres_back"

    def test_sqlite_only_config_never_alerts(self) -> None:
        mon = DbMonitor()
        assert mon.evaluate(configured_postgres=False, active="sqlite", postgres_reachable=None) is None

    def test_alert_text_mentions_migration(self) -> None:
        assert "migrate_to_postgres" in format_db_alert("postgres_back", "2026-09-30T21:00:00+00:00")
        assert "SQLite fallback" in format_db_alert("failover", None)


# ── Integration: needs a disposable Postgres (HRCC_TEST_PG_URL) ────────────

PG_URL = os.environ.get("HRCC_TEST_PG_URL", "")
needs_pg = pytest.mark.skipif(not PG_URL, reason="set HRCC_TEST_PG_URL to a disposable Postgres to run")


@pytest.fixture()
def clean_pg() -> str:
    import psycopg
    with psycopg.connect(PG_URL, autocommit=True) as conn:
        conn.execute("DROP SCHEMA public CASCADE")
        conn.execute("CREATE SCHEMA public")
    return PG_URL


@needs_pg
class TestMigrateToPostgres:
    def _seed(self, temp_sqlite: Path) -> None:
        db_mod.init_db()
        for i in range(3):
            db_mod.create_ticket(channel_id=1, message_id=1, author_id=10 + i, author_name=f"a{i}",
                                 category="TECH", urgency="P1", poc_name="sreesanth", description=f"t{i}")
        db_mod.upsert_ambassador_profile(ambassador_id=10, ambassador_name="a0")
        db_mod.close_db()

    def test_dry_run_writes_nothing(self, temp_sqlite: Path, clean_pg: str) -> None:
        import psycopg
        from hrcc_bot.core.migrate_to_postgres import migrate
        self._seed(temp_sqlite)
        report = migrate(temp_sqlite, clean_pg, dry_run=True)
        assert report["escalation_tickets"].rows == 3
        with psycopg.connect(clean_pg) as conn:
            exists = conn.execute("SELECT to_regclass('escalation_tickets')").fetchone()[0]
        assert exists is None  # schema creation rolled back too

    def test_copies_rows_and_advances_sequence(self, temp_sqlite: Path, clean_pg: str) -> None:
        import psycopg
        from hrcc_bot.core.migrate_to_postgres import migrate
        self._seed(temp_sqlite)
        report = migrate(temp_sqlite, clean_pg)
        assert report["escalation_tickets"].inserted == 3
        assert report["ambassador_profiles"].inserted == 1
        with psycopg.connect(clean_pg) as conn:
            codes = [r[0] for r in conn.execute("SELECT ticket_code FROM escalation_tickets ORDER BY id")]
            next_id = conn.execute(
                "INSERT INTO escalation_tickets (ticket_code, channel_id, message_id, author_id, author_name, "
                "category, urgency, poc_name, created_at, updated_at) VALUES "
                "('X', 1, 1, 1, 'x', 'OPS', 'P2', 's', 'now', 'now') RETURNING id"
            ).fetchone()[0]
        assert codes == ["HRCC-101", "HRCC-102", "HRCC-103"]
        assert next_id == 4  # sequence moved past copied ids

    def test_rerun_skips_existing_rows(self, temp_sqlite: Path, clean_pg: str) -> None:
        from hrcc_bot.core.migrate_to_postgres import migrate
        self._seed(temp_sqlite)
        migrate(temp_sqlite, clean_pg)
        again = migrate(temp_sqlite, clean_pg)
        assert again["escalation_tickets"].inserted == 0
        assert again["escalation_tickets"].skipped == 3

    def test_main_clears_marker_and_blocks_on_conflict(
        self, temp_sqlite: Path, clean_pg: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from hrcc_bot.core.migrate_to_postgres import main
        self._seed(temp_sqlite)
        monkeypatch.setattr(settings, "database_url", clean_pg)
        db_mod._failover_marker().write_text("2026-01-01T00:00:00+00:00")

        assert main([]) == 0
        assert db_mod.failover_pending_since() is None

        db_mod._failover_marker().write_text("2026-01-02T00:00:00+00:00")
        assert main([]) == 2  # all rows now conflict
        assert db_mod.failover_pending_since() is not None
        assert main(["--force"]) == 0
        assert db_mod.failover_pending_since() is None
