from __future__ import annotations

import os
from pathlib import Path

import pytest

os.environ.setdefault("DISCORD_BOT_TOKEN", "test-token")

from src.db import (
    close_db,
    create_ticket,
    get_ambassador_events,
    get_ambassador_profile,
    get_conversation_turns,
    get_ticket,
    init_db,
    record_event_submission,
    save_conversation_turn,
    update_ambassador_stage,
    upsert_ambassador_profile,
)
from src.tools import (
    calculate_reward_tier,
    create_escalation_ticket,
    lookup_ambassador_profile,
    lookup_ticket_status,
    search_handbook_knowledge,
)


@pytest.fixture(autouse=True)
def _use_temp_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import src.db as db_mod

    test_db = tmp_path / "test.db"
    monkeypatch.setattr(db_mod, "_DB_PATH", test_db)
    if hasattr(db_mod, "_local"):
        db_mod._local.conn = None  # type: ignore[attr-defined]
    init_db()
    yield
    close_db()


class TestToolCreateTicket:
    def test_creates_ticket_and_returns_code(self) -> None:
        result = create_escalation_ticket.invoke(
            {"category": "TECH", "urgency": "P1", "description": "HRW login broken", "poc_name": "sreesanth"}
        )
        assert "HRCC-" in result
        assert "TECH" in result
        assert "Sreesanth" in result

    def test_invalid_category_reports_error(self) -> None:
        result = create_escalation_ticket.invoke(
            {"category": "INVALID", "urgency": "P1", "description": "test", "poc_name": "sreesanth"}
        )
        assert "Failed" in result


class TestToolLookupTicket:
    def test_found(self) -> None:
        ticket = create_ticket(
            channel_id=1, message_id=1, author_id=1, author_name="Test",
            category="OPS", urgency="P2", poc_name="sanskruti", description="test issue",
        )
        result = lookup_ticket_status.invoke({"ticket_code": ticket["ticket_code"]})
        assert ticket["ticket_code"] in result
        assert "PENDING" in result

    def test_not_found(self) -> None:
        result = lookup_ticket_status.invoke({"ticket_code": "HRCC-99999"})
        assert "No ticket found" in result


class TestToolRewardTier:
    def test_under_300(self) -> None:
        result = calculate_reward_tier.invoke({"participant_count": 150})
        assert "No" in result or "no" in result.lower()

    def test_300_plus(self) -> None:
        result = calculate_reward_tier.invoke({"participant_count": 400})
        assert "Yes" in result or "Merch" in result or "SPOC" in result


class TestToolHandbookSearch:
    def test_returns_results(self) -> None:
        from src.knowledge import load_references
        load_references()
        result = search_handbook_knowledge.invoke({"query": "HRW assessment contest setup"})
        assert isinstance(result, str)
        assert len(result) > 20

    def test_empty_query(self) -> None:
        result = search_handbook_knowledge.invoke({"query": "zzzznonexistent"})
        assert isinstance(result, str)


class TestToolAmbassadorProfile:
    def test_no_events(self) -> None:
        result = lookup_ambassador_profile.invoke({"ambassador_id": 99999})
        assert "No events" in result

    def test_with_events(self) -> None:
        record_event_submission(
            ambassador_id=42, ambassador_name="TestAmb", event_name="CodeFest",
            participant_count=200, reward_tier="Standard", merch_eligible=False,
        )
        result = lookup_ambassador_profile.invoke({"ambassador_id": 42})
        assert "TestAmb" in result
        assert "CodeFest" in result


class TestAmbassadorProfiles:
    def test_upsert_creates_profile(self) -> None:
        p = upsert_ambassador_profile(ambassador_id=1, ambassador_name="Alice", college_name="MIT")
        assert p["ambassador_name"] == "Alice"
        assert p["college_name"] == "MIT"
        assert p["current_stage"] == "PLANNING"

    def test_upsert_updates_existing(self) -> None:
        upsert_ambassador_profile(ambassador_id=2, ambassador_name="Bob", college_name="Stanford")
        p = upsert_ambassador_profile(ambassador_id=2, ambassador_name="Bob Updated", current_stage="LIVE")
        assert p["ambassador_name"] == "Bob Updated"
        assert p["current_stage"] == "LIVE"
        assert p["college_name"] == "Stanford"

    def test_update_stage(self) -> None:
        upsert_ambassador_profile(ambassador_id=3, ambassador_name="Charlie")
        updated = update_ambassador_stage(3, "REWARDS")
        assert updated is not None
        assert updated["current_stage"] == "REWARDS"

    def test_get_nonexistent_profile(self) -> None:
        assert get_ambassador_profile(99999) is None

    def test_stage_lifecycle(self) -> None:
        upsert_ambassador_profile(ambassador_id=4, ambassador_name="Diana")
        for stage in ("PLANNING", "SETUP", "OUTREACH", "LIVE", "REWARDS"):
            update_ambassador_stage(4, stage)
            p = get_ambassador_profile(4)
            assert p is not None
            assert p["current_stage"] == stage


class TestConversationPersistence:
    def test_save_and_retrieve_turns(self) -> None:
        save_conversation_turn(100, "user", "Hello there")
        save_conversation_turn(100, "assistant", "Hi! How can I help?")
        save_conversation_turn(100, "user", "What are reward tiers?")

        turns = get_conversation_turns(100, limit=10)
        assert len(turns) == 3
        assert turns[0]["role"] == "user"
        assert turns[0]["content"] == "Hello there"
        assert turns[2]["role"] == "user"

    def test_limit_respected(self) -> None:
        for i in range(20):
            save_conversation_turn(200, "user", f"msg {i}")
        turns = get_conversation_turns(200, limit=5)
        assert len(turns) == 5

    def test_separate_users(self) -> None:
        save_conversation_turn(300, "user", "from user 300")
        save_conversation_turn(301, "user", "from user 301")
        turns_300 = get_conversation_turns(300)
        turns_301 = get_conversation_turns(301)
        assert len(turns_300) == 1
        assert len(turns_301) == 1
        assert turns_300[0]["content"] == "from user 300"

    def test_context_memory_integration(self) -> None:
        from src.context import ConversationMemory
        mem = ConversationMemory()
        mem.add_user_message(400, "test message")
        mem.add_assistant_message(400, "test reply")

        db_turns = get_conversation_turns(400)
        assert len(db_turns) == 2

        mem2 = ConversationMemory()
        history = mem2.get_history(400)
        assert len(history) == 2
        assert history[0]["content"] == "test message"
