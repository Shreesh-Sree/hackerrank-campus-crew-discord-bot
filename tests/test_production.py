from __future__ import annotations

import os
import sqlite3
import tempfile
from pathlib import Path

import pytest

os.environ.setdefault("DISCORD_BOT_TOKEN", "test-token")

from src.csv_validator import ContestResult, parse_contest_csv
from src.db import (
    _DB_PATH,
    close_db,
    create_ticket,
    get_ticket,
    init_db,
    record_event_submission,
    update_ticket_status,
)
from src.knowledge import (
    _chunk_all_references,
    _reference_docs,
    build_context_block,
    load_knowledge,
    load_references,
    retrieve_relevant_chunks,
)
from src.rubrics import detect_escalation_target


# ── Fixtures ──────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _use_temp_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import src.db as db_mod

    test_db = tmp_path / "test_hrcc.db"
    monkeypatch.setattr(db_mod, "_DB_PATH", test_db)
    monkeypatch.setattr(db_mod, "_conn", None)
    init_db()
    yield
    close_db()


# ── Database Tests ────────────────────────────────────────────────────────


class TestDatabase:
    def test_init_creates_tables(self, tmp_path: Path) -> None:
        import src.db as db_mod

        conn = sqlite3.connect(str(db_mod._DB_PATH))
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
        table_names = {t[0] for t in tables}
        assert "escalation_tickets" in table_names
        assert "ambassador_events" in table_names
        conn.close()

    def test_create_and_get_ticket(self) -> None:
        ticket = create_ticket(
            channel_id=123,
            message_id=456,
            author_id=789,
            author_name="TestUser",
            category="TECH",
            urgency="P1",
            poc_name="sreesanth",
            description="HRW login broken",
        )
        assert ticket["ticket_code"].startswith("HRCC-")
        assert ticket["status"] == "PENDING"
        assert ticket["category"] == "TECH"
        assert ticket["urgency"] == "P1"

        fetched = get_ticket(ticket["ticket_code"])
        assert fetched is not None
        assert fetched["author_name"] == "TestUser"

    def test_ticket_state_transitions(self) -> None:
        ticket = create_ticket(
            channel_id=100,
            message_id=200,
            author_id=300,
            author_name="Ambassador1",
            category="OPS",
            urgency="P2",
            poc_name="sanskruti",
            description="Reward activation query",
        )
        code = ticket["ticket_code"]

        updated = update_ticket_status(code, "ACKNOWLEDGED")
        assert updated is not None
        assert updated["status"] == "ACKNOWLEDGED"

        resolved = update_ticket_status(
            code, "RESOLVED", resolution_notes="Rewards activated successfully"
        )
        assert resolved is not None
        assert resolved["status"] == "RESOLVED"
        assert resolved["resolution_notes"] == "Rewards activated successfully"

    def test_nonexistent_ticket_returns_none(self) -> None:
        assert get_ticket("HRCC-99999") is None

    def test_record_event_submission(self) -> None:
        event = record_event_submission(
            ambassador_id=1001,
            ambassador_name="TestAmbassador",
            college_name="St. Joseph's Engineering College",
            event_name="CodeStorm 2026",
            event_date="2026-09-19",
            platform="HRW",
            participant_count=350,
            reward_tier="Tier 300+",
            merch_eligible=True,
            csv_sha256="abc123",
        )
        assert event["ambassador_name"] == "TestAmbassador"
        assert event["participant_count"] == 350
        assert event["merch_eligible"] == 1


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

    def test_canva_csv_generation(self) -> None:
        csv_bytes = self._make_csv([
            ["Full Name", "Email Address", "Score"],
            ["Alice Johnson", "alice@example.com", "300"],
            ["Bob Smith", "bob@example.com", "250"],
        ])
        result = parse_contest_csv(
            csv_bytes,
            event_name="CodeFiesta",
            event_date="2026-09-19",
            college_name="IIT Madras",
        )
        assert "Full Name,Email Address,College Name,Event Name,Event Date,Rank,Score" in result.canva_csv
        assert "Alice Johnson" in result.canva_csv
        assert "IIT Madras" in result.canva_csv
        assert result.csv_sha256

    def test_invalid_email_warning(self) -> None:
        csv_bytes = self._make_csv([
            ["Name", "Email", "Score"],
            ["Alice", "not-an-email", "100"],
        ])
        result = parse_contest_csv(csv_bytes)
        assert any("Invalid email" in w for w in result.warnings)

    def test_empty_csv_warning(self) -> None:
        result = parse_contest_csv(b"")
        assert any("no headers" in w.lower() or "empty" in w.lower() for w in result.warnings)

    def test_winners_sorted_by_score(self) -> None:
        csv_bytes = self._make_csv([
            ["Name", "Score"],
            ["Low", "10"],
            ["High", "500"],
            ["Mid", "200"],
        ])
        result = parse_contest_csv(csv_bytes)
        assert result.winners[0]["name"] == "High"
        assert result.winners[1]["name"] == "Mid"
        assert result.winners[2]["name"] == "Low"


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


# ── Escalation Cooldown Tests ─────────────────────────────────────────────


class TestEscalationCooldown:
    def test_no_cooldown_on_first_ticket(self) -> None:
        from src.db import get_recent_tickets

        recent = get_recent_tickets(author_id=999, category="TECH", hours=2)
        assert len(recent) == 0

    def test_cooldown_after_ticket_created(self) -> None:
        from src.db import get_recent_tickets

        create_ticket(
            channel_id=10,
            message_id=20,
            author_id=555,
            author_name="CooldownTest",
            category="TECH",
            urgency="P1",
            poc_name="sreesanth",
        )
        recent = get_recent_tickets(author_id=555, category="TECH", hours=2)
        assert len(recent) >= 1

    def test_different_category_no_cooldown(self) -> None:
        from src.db import get_recent_tickets

        create_ticket(
            channel_id=10,
            message_id=20,
            author_id=666,
            author_name="CatTest",
            category="OPS",
            urgency="P2",
            poc_name="sanskruti",
        )
        recent = get_recent_tickets(author_id=666, category="TECH", hours=2)
        assert len(recent) == 0


# ── Escalation Router Detection Tests ─────────────────────────────────────


class TestEscalationRouterDetection:
    def test_p0_urgency_classification(self) -> None:
        from src.escalation import _classify_urgency

        assert _classify_urgency("contest is live and students getting 500 error") == "P0"

    def test_p1_urgency_classification(self) -> None:
        from src.escalation import _classify_urgency

        assert _classify_urgency("My HRW invitation is still pending") == "P1"

    def test_p2_urgency_classification(self) -> None:
        from src.escalation import _classify_urgency

        assert _classify_urgency("Can I get the certificate template?") == "P2"

    def test_escalation_target_detection(self) -> None:
        assert detect_escalation_target("I need the reward activated for winners") == "sanskruti"
        assert detect_escalation_target("There is a 500 error on the platform") == "sreesanth"
        assert detect_escalation_target("Can I get the official logo and brand assets?") == "nitish"
