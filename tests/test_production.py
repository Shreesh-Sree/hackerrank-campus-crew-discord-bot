from __future__ import annotations

import os
import sqlite3
from pathlib import Path

import pytest

os.environ.setdefault("DISCORD_BOT_TOKEN", "test-token")

from src.config import settings
from src.context import ConversationMemory
from src.csv_validator import parse_contest_csv
from src.db import (
    close_db,
    create_ticket,
    get_ambassador_events,
    get_ticket,
    get_ticket_stats,
    init_db,
    record_event_submission,
    update_ticket_status,
)
from src.knowledge import (
    build_context_block,
    check_and_reload,
    load_knowledge,
    load_references,
    reload_all,
    retrieve_relevant_chunks,
)
from src.rubrics import detect_escalation_target


# ── Fixtures ──────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _use_temp_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import src.db as db_mod

    test_db = tmp_path / "test_hrcc.db"
    monkeypatch.setattr(db_mod, "_DB_PATH", test_db)
    if hasattr(db_mod, "_local"):
        db_mod._local.conn = None  # type: ignore[attr-defined]
    init_db()
    yield
    close_db()


# ── Database Tests ────────────────────────────────────────────────────────


class TestDatabase:
    def test_init_creates_tables(self) -> None:
        import src.db as db_mod

        conn = sqlite3.connect(str(db_mod._DB_PATH))
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
        table_names = {t[0] for t in tables}
        assert "escalation_tickets" in table_names
        assert "ambassador_events" in table_names
        conn.close()

    def test_init_creates_indexes(self) -> None:
        import src.db as db_mod

        conn = sqlite3.connect(str(db_mod._DB_PATH))
        indexes = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index'"
        ).fetchall()
        index_names = {i[0] for i in indexes}
        assert "idx_tickets_author_cat" in index_names
        assert "idx_tickets_code" in index_names
        assert "idx_events_ambassador" in index_names
        conn.close()

    def test_create_and_get_ticket(self) -> None:
        ticket = create_ticket(
            channel_id=123, message_id=456, author_id=789, author_name="TestUser",
            category="TECH", urgency="P1", poc_name="sreesanth", description="HRW login broken",
        )
        assert ticket["ticket_code"].startswith("HRCC-")
        assert ticket["status"] == "PENDING"
        assert ticket["category"] == "TECH"
        assert ticket["urgency"] == "P1"

        fetched = get_ticket(ticket["ticket_code"])
        assert fetched is not None
        assert fetched["author_name"] == "TestUser"
        assert fetched["description"] == "HRW login broken"

    def test_ticket_state_transitions(self) -> None:
        ticket = create_ticket(
            channel_id=100, message_id=200, author_id=300, author_name="Ambassador1",
            category="OPS", urgency="P2", poc_name="sanskruti", description="Reward activation query",
        )
        code = ticket["ticket_code"]

        updated = update_ticket_status(code, "ACKNOWLEDGED")
        assert updated is not None
        assert updated["status"] == "ACKNOWLEDGED"

        resolved = update_ticket_status(code, "RESOLVED", resolution_notes="Rewards activated successfully")
        assert resolved is not None
        assert resolved["status"] == "RESOLVED"
        assert resolved["resolution_notes"] == "Rewards activated successfully"
        assert resolved["updated_at"] >= resolved["created_at"]

    def test_nonexistent_ticket_returns_none(self) -> None:
        assert get_ticket("HRCC-99999") is None

    def test_update_nonexistent_ticket(self) -> None:
        result = update_ticket_status("HRCC-99999", "RESOLVED")
        assert result is None

    def test_ticket_stats(self) -> None:
        create_ticket(
            channel_id=1, message_id=1, author_id=1, author_name="A",
            category="TECH", urgency="P1", poc_name="sreesanth",
        )
        create_ticket(
            channel_id=2, message_id=2, author_id=2, author_name="B",
            category="OPS", urgency="P2", poc_name="sanskruti",
        )
        stats = get_ticket_stats()
        assert stats["PENDING"] == 2
        assert stats["total"] == 2

    def test_record_and_get_ambassador_events(self) -> None:
        event = record_event_submission(
            ambassador_id=1001, ambassador_name="TestAmbassador",
            college_name="St. Joseph's Engineering College", event_name="CodeStorm 2026",
            event_date="2026-09-19", platform="HRW", participant_count=350,
            reward_tier="Tier 300+", merch_eligible=True, csv_sha256="abc123",
        )
        assert event["ambassador_name"] == "TestAmbassador"
        assert event["participant_count"] == 350
        assert event["merch_eligible"] == 1

        events = get_ambassador_events(1001)
        assert len(events) == 1
        assert events[0]["event_name"] == "CodeStorm 2026"

    def test_multiple_tickets_unique_codes(self) -> None:
        codes = set()
        for i in range(5):
            t = create_ticket(
                channel_id=i, message_id=i, author_id=i, author_name=f"User{i}",
                category="TECH", urgency="P2", poc_name="sreesanth",
            )
            codes.add(t["ticket_code"])
        assert len(codes) == 5


# ── CSV Validator Tests ───────────────────────────────────────────────────


class TestCSVValidator:
    def _make_csv(self, rows: list[list[str]]) -> bytes:
        lines = [",".join(row) for row in rows]
        return "\n".join(lines).encode("utf-8")

    def test_basic_csv_parsing(self) -> None:
        csv_bytes = self._make_csv([
            ["Full Name", "Email", "Score", "Rank"],
            ["Alice", "alice@example.com", "300", "1"],
            ["Bob", "bob@example.com", "250", "2"],
            ["Charlie", "charlie@example.com", "0", "3"],
        ])
        result = parse_contest_csv(csv_bytes, event_name="Test Event")
        assert result.total_rows == 3
        assert result.active_participants == 2
        assert result.inactive_count == 1

    def test_reward_tier_under_300(self) -> None:
        rows = [["Name", "Score"]] + [[f"Student{i}", str(i + 1)] for i in range(100)]
        result = parse_contest_csv(self._make_csv(rows))
        assert result.reward_tier == "Standard (< 300)"
        assert result.merch_eligible is False

    def test_reward_tier_300_plus(self) -> None:
        rows = [["Name", "Score"]] + [[f"Student{i}", str(i + 1)] for i in range(350)]
        result = parse_contest_csv(self._make_csv(rows))
        assert result.reward_tier == "Tier 300+"
        assert result.merch_eligible is True

    def test_reward_tier_exactly_300(self) -> None:
        rows = [["Name", "Score"]] + [[f"Student{i}", str(i + 1)] for i in range(300)]
        result = parse_contest_csv(self._make_csv(rows))
        assert result.merch_eligible is True

    def test_canva_csv_generation(self) -> None:
        csv_bytes = self._make_csv([
            ["Full Name", "Email Address", "Score"],
            ["Alice Johnson", "alice@example.com", "300"],
            ["Bob Smith", "bob@example.com", "250"],
        ])
        result = parse_contest_csv(
            csv_bytes, event_name="CodeFiesta", event_date="2026-09-19", college_name="IIT Madras",
        )
        assert "Full Name,Email Address,College Name,Event Name,Event Date,Rank,Score" in result.canva_csv
        assert "Alice Johnson" in result.canva_csv
        assert "IIT Madras" in result.canva_csv
        assert len(result.csv_sha256) == 64

    def test_invalid_email_warning(self) -> None:
        csv_bytes = self._make_csv([["Name", "Email", "Score"], ["Alice", "not-an-email", "100"]])
        result = parse_contest_csv(csv_bytes)
        assert any("Invalid email" in w for w in result.warnings)

    def test_empty_csv_warning(self) -> None:
        result = parse_contest_csv(b"")
        assert any("no headers" in w.lower() or "empty" in w.lower() for w in result.warnings)

    def test_winners_sorted_by_score(self) -> None:
        csv_bytes = self._make_csv([["Name", "Score"], ["Low", "10"], ["High", "500"], ["Mid", "200"]])
        result = parse_contest_csv(csv_bytes)
        assert result.winners[0]["name"] == "High"
        assert result.winners[1]["name"] == "Mid"
        assert result.winners[2]["name"] == "Low"

    def test_winners_capped_at_10(self) -> None:
        rows = [["Name", "Score"]] + [[f"Student{i}", str(100 - i)] for i in range(20)]
        result = parse_contest_csv(self._make_csv(rows))
        assert len(result.winners) == 10

    def test_utf8_bom_handling(self) -> None:
        result = parse_contest_csv(b"\xef\xbb\xbfName,Score\nAlice,100\n")
        assert result.active_participants == 1

    def test_latin1_fallback(self) -> None:
        result = parse_contest_csv("Name,Score\nJos\xe9,100\n".encode("latin-1"))
        assert result.active_participants == 1

    def test_column_alias_detection(self) -> None:
        csv_bytes = self._make_csv([
            ["Student Name", "Mail", "Total Score", "Position"],
            ["Alice", "alice@example.com", "300", "1"],
        ])
        result = parse_contest_csv(csv_bytes)
        assert result.active_participants == 1


# ── Knowledge & RAG Retrieval Tests ───────────────────────────────────────


class TestKnowledgeRAG:
    def test_load_knowledge_returns_dict(self) -> None:
        kb = load_knowledge()
        assert isinstance(kb, dict)
        assert "platforms" in kb
        assert "rewards" in kb

    def test_load_references(self) -> None:
        refs = load_references()
        assert isinstance(refs, dict)
        if refs:
            assert any(k in refs for k in ["handbook", "sops", "templates"])

    def test_build_context_block_contains_platforms(self) -> None:
        ctx = build_context_block()
        assert "HackerRank for Work" in ctx or "HRW" in ctx

    def test_retrieve_relevant_chunks_hrw(self) -> None:
        load_references()
        chunks = retrieve_relevant_chunks("How do I create an assessment on HRW?")
        assert isinstance(chunks, list)

    def test_retrieve_relevant_chunks_rewards(self) -> None:
        load_references()
        chunks = retrieve_relevant_chunks("What are the reward tiers for 300 participants?")
        assert isinstance(chunks, list)

    def test_retrieve_empty_query(self) -> None:
        assert retrieve_relevant_chunks("") == []

    def test_build_context_with_query(self) -> None:
        ctx = build_context_block(query="certificate canva template")
        assert isinstance(ctx, str)
        assert "Certificate" in ctx or "certificate" in ctx

    def test_hot_reload_no_change(self) -> None:
        load_knowledge()
        load_references()
        assert check_and_reload() is False

    def test_force_reload(self) -> None:
        load_knowledge()
        load_references()
        reload_all()
        kb = load_knowledge()
        assert "platforms" in kb


# ── Conversation Memory Tests ─────────────────────────────────────────────


class TestConversationMemory:
    def test_add_and_get_history(self) -> None:
        mem = ConversationMemory()
        mem.add_user_message(1, "Hello")
        mem.add_assistant_message(1, "Hi there")
        history = mem.get_history(1)
        assert len(history) == 2
        assert history[0]["role"] == "user"
        assert history[1]["role"] == "assistant"

    def test_empty_history(self) -> None:
        assert ConversationMemory().get_history(999) == []

    def test_sliding_window_truncation(self) -> None:
        mem = ConversationMemory()
        for i in range(50):
            mem.add_user_message(1, f"msg {i}")
            mem.add_assistant_message(1, f"reply {i}")
        history = mem.get_history(1)
        assert len(history) <= 16

    def test_lru_eviction(self) -> None:
        mem = ConversationMemory(max_users=3)
        mem.add_user_message(1, "a")
        mem.add_user_message(2, "b")
        mem.add_user_message(3, "c")
        mem.add_user_message(4, "d")
        assert mem.get_history(1) == []
        assert len(mem.get_history(2)) == 1

    def test_clear(self) -> None:
        mem = ConversationMemory()
        mem.add_user_message(1, "hello")
        mem.clear(1)
        assert mem.get_history(1) == []

    def test_lru_touch_on_access(self) -> None:
        mem = ConversationMemory(max_users=3)
        mem.add_user_message(1, "a")
        mem.add_user_message(2, "b")
        mem.add_user_message(3, "c")
        mem.get_history(1)
        mem.add_user_message(4, "d")
        assert len(mem.get_history(1)) == 1
        assert mem.get_history(2) == []


# ── Escalation Cooldown Tests ─────────────────────────────────────────────


class TestEscalationCooldown:
    def test_no_cooldown_on_first_ticket(self) -> None:
        from src.db import get_recent_tickets
        assert len(get_recent_tickets(author_id=999, category="TECH", hours=2)) == 0

    def test_cooldown_after_ticket_created(self) -> None:
        from src.db import get_recent_tickets
        create_ticket(
            channel_id=10, message_id=20, author_id=555, author_name="CooldownTest",
            category="TECH", urgency="P1", poc_name="sreesanth",
        )
        assert len(get_recent_tickets(author_id=555, category="TECH", hours=2)) >= 1

    def test_different_category_no_cooldown(self) -> None:
        from src.db import get_recent_tickets
        create_ticket(
            channel_id=10, message_id=20, author_id=666, author_name="CatTest",
            category="OPS", urgency="P2", poc_name="sanskruti",
        )
        assert len(get_recent_tickets(author_id=666, category="TECH", hours=2)) == 0

    def test_resolved_tickets_dont_block(self) -> None:
        from src.db import get_recent_tickets
        t = create_ticket(
            channel_id=10, message_id=20, author_id=777, author_name="ResolveTest",
            category="TECH", urgency="P1", poc_name="sreesanth",
        )
        update_ticket_status(t["ticket_code"], "RESOLVED", resolution_notes="fixed")
        assert len(get_recent_tickets(author_id=777, category="TECH", hours=2)) == 0


# ── Escalation Router Detection Tests ─────────────────────────────────────


class TestEscalationRouterDetection:
    def test_p0_urgency(self) -> None:
        from src.escalation import _classify_urgency
        assert _classify_urgency("contest is live and students getting 500 error") == "P0"
        assert _classify_urgency("this is urgent! event starts in 30 minutes") == "P0"

    def test_p1_urgency(self) -> None:
        from src.escalation import _classify_urgency
        assert _classify_urgency("My HRW invitation is still pending") == "P1"
        assert _classify_urgency("reward not activated for winners") == "P1"

    def test_p2_urgency(self) -> None:
        from src.escalation import _classify_urgency
        assert _classify_urgency("Can I get the certificate template?") == "P2"

    def test_escalation_targets(self) -> None:
        assert detect_escalation_target("I need the reward activated for winners") == "sanskruti"
        assert detect_escalation_target("There is a 500 error on the platform") == "sreesanth"
        assert detect_escalation_target("Can I get the official logo and brand assets?") == "nitish"


# ── Rate Limiter Tests ────────────────────────────────────────────────────


class TestRateLimiter:
    def test_allows_normal_traffic(self) -> None:
        from bot import _check_rate_limit, _rate_buckets
        _rate_buckets.clear()
        for _ in range(5):
            assert _check_rate_limit(12345) is True

    def test_blocks_flood(self) -> None:
        from bot import _check_rate_limit, _rate_buckets
        _rate_buckets.clear()
        for _ in range(settings.rate_limit_per_minute):
            _check_rate_limit(99999)
        assert _check_rate_limit(99999) is False


# ── Graph Pipeline State Tests ────────────────────────────────────────────


class TestGraphPipeline:
    def test_state_has_conversation_history(self) -> None:
        from src.graph import PipelineState
        state: PipelineState = {
            "message_content": "test", "author_name": "test", "author_id": 1,
            "channel_id": 1, "is_dm": False, "is_mention": False, "is_bot": False,
            "conversation_history": [{"role": "user", "content": "prior msg"}],
        }
        assert state["conversation_history"][0]["role"] == "user"

    def test_skillup_hosting_regex(self) -> None:
        from src.graph import _SKILLUP_HOST_RE
        assert _SKILLUP_HOST_RE.search("Can I host my contest on SkillUp?")
        assert _SKILLUP_HOST_RE.search("I want to use skillup for my hackathon")
        assert not _SKILLUP_HOST_RE.search("What is SkillUp?")
