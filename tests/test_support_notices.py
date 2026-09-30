from __future__ import annotations

import os
from pathlib import Path

import pytest

os.environ.setdefault("DISCORD_BOT_TOKEN", "test-token")

from hrcc_bot.core.db import (
    _execute,
    add_support_notice,
    close_db,
    deactivate_support_notice,
    get_active_support_notices,
    init_db,
)
from hrcc_bot.pipeline.knowledge import build_context_block


@pytest.fixture(autouse=True)
def _use_temp_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import hrcc_bot.core.db as db_mod

    monkeypatch.setattr(db_mod, "_SQLITE_PATH", tmp_path / "test.db")
    monkeypatch.setattr(db_mod, "_using_postgres", False)
    db_mod._local.sqlite_conn = None  # type: ignore[attr-defined]
    init_db()
    yield
    close_db()


MAINT = "HRW maintenance Sunday 02:00-04:00 IST"


class TestSupportNotices:
    def test_add_returns_row_and_is_active(self) -> None:
        notice = add_support_notice(message=MAINT, author_id=1, author_name="lead", expires_in_days=7)
        assert notice is not None and notice["id"] >= 1
        assert [n["message"] for n in get_active_support_notices()] == [MAINT]

    def test_expired_notice_excluded(self) -> None:
        notice = add_support_notice(message=MAINT, author_id=1, author_name="lead")
        _execute("UPDATE support_notices SET expires_at=? WHERE id=?", ("2000-01-01T00:00:00+00:00", notice["id"]))
        assert get_active_support_notices() == []

    def test_deactivate(self) -> None:
        notice = add_support_notice(message=MAINT, author_id=1, author_name="lead")
        assert deactivate_support_notice(notice["id"]) is True
        assert deactivate_support_notice(notice["id"]) is False
        assert get_active_support_notices() == []


class TestNoticeInKnowledgeContext:
    def test_active_notice_injected_first(self) -> None:
        add_support_notice(message=MAINT, author_id=1, author_name="lead")
        context = build_context_block("is there maintenance on sunday?")
        assert context.startswith("## ACTIVE OPERATIONAL NOTICES")
        assert MAINT in context

    def test_no_section_without_notices(self) -> None:
        assert "OPERATIONAL NOTICES" not in build_context_block("rewards")
