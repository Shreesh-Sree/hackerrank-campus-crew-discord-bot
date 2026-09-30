from __future__ import annotations

import asyncio
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

os.environ.setdefault("DISCORD_BOT_TOKEN", "test-token")

from langchain_core.messages import AIMessage

from src.config import settings
from src.db import _execute, close_db, create_ticket, get_recent_tickets, get_ticket_stats, init_db
from src.escalation import EscalationOutcome, format_outcome, open_escalation, resolve_lead
from src.graph import extract_escalation_request


@pytest.fixture(autouse=True)
def _use_temp_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import src.db as db_mod

    monkeypatch.setattr(db_mod, "_SQLITE_PATH", tmp_path / "test.db")
    monkeypatch.setattr(db_mod, "_using_postgres", False)
    db_mod._local.sqlite_conn = None  # type: ignore[attr-defined]
    init_db()
    yield
    close_db()


class _FakeDM:
    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []

    async def send(self, **kwargs: Any) -> None:
        self.sent.append(kwargs)


class _FakeUser:
    def __init__(self) -> None:
        self.dm = _FakeDM()

    async def create_dm(self) -> _FakeDM:
        return self.dm

    def __str__(self) -> str:
        return "lead#0001"


class _FakeClient:
    def __init__(self) -> None:
        self.user = _FakeUser()
        self.fetched: list[int] = []

    async def fetch_user(self, user_id: int) -> _FakeUser:
        self.fetched.append(user_id)
        return self.user


def _open(client: _FakeClient, description: str, author_id: int = 42, lead_key: str = "sreesanth") -> EscalationOutcome:
    return asyncio.run(open_escalation(
        client=client,  # type: ignore[arg-type]
        channel_id=1001,
        message_id=2002,
        author_id=author_id,
        author_name="amb#1234",
        lead_key=lead_key,
        description=description,
    ))


def _insert_ticket_at(author_id: int, created_at: datetime) -> None:
    ts = created_at.isoformat()
    _execute(
        """INSERT INTO escalation_tickets
           (ticket_code, channel_id, message_id, author_id, author_name, category, urgency,
            poc_name, poc_id, status, description, resolution_notes, created_at, updated_at)
           VALUES (?, 1, 1, ?, 'x', 'TECH', 'P1', 'sreesanth', '', 'PENDING', '', '', ?, ?)""",
        (f"OLD-{author_id}-{ts}", author_id, ts, ts),
    )


class TestCooldownWindow:
    def test_ticket_older_than_window_ignored(self) -> None:
        _insert_ticket_at(10, datetime.now(timezone.utc) - timedelta(hours=3))
        assert get_recent_tickets(10, "TECH", hours=2) == []

    def test_ticket_inside_window_counted(self) -> None:
        _insert_ticket_at(11, datetime.now(timezone.utc) - timedelta(minutes=30))
        assert len(get_recent_tickets(11, "TECH", hours=2)) == 1


class TestOpenEscalation:
    def test_creates_ticket_and_dms_lead(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(settings, "poc_discord_sreesanth", "555")
        monkeypatch.setattr(settings, "enable_dm_routing", True)
        client = _FakeClient()

        outcome = _open(client, "HRW invite never arrived")

        assert outcome.ticket is not None
        assert outcome.dm_delivered is True
        assert outcome.ticket["author_id"] == 42
        assert outcome.ticket["channel_id"] == 1001
        assert client.fetched == [555]
        assert len(client.user.dm.sent) == 1
        assert outcome.ticket["ticket_code"] in client.user.dm.sent[0]["embed"].title

    def test_second_ticket_same_category_is_duplicate(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(settings, "poc_discord_sreesanth", "555")
        client = _FakeClient()

        first = _open(client, "HRW login issue")
        second = _open(client, "HRW login issue again")

        assert second.ticket is None
        assert second.duplicate_of is not None
        assert second.duplicate_of["ticket_code"] == first.ticket["ticket_code"]  # type: ignore[index]
        assert len(client.user.dm.sent) == 1
        assert get_ticket_stats()["total"] == 1

    def test_p0_bypasses_cooldown(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(settings, "enable_p0_override", True)
        client = _FakeClient()

        _open(client, "login issue")
        emergency = _open(client, "contest is live and students getting error")

        assert emergency.ticket is not None
        assert emergency.ticket["urgency"] == "P0"

    def test_missing_poc_id_still_logs_ticket(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(settings, "poc_discord_nitish", "")
        client = _FakeClient()

        outcome = _open(client, "need logo files", lead_key="nitish")

        assert outcome.ticket is not None
        assert outcome.dm_delivered is False
        assert client.fetched == []
        assert "couldn't DM" in format_outcome(outcome)


class TestFormatOutcome:
    def test_dispatched(self) -> None:
        ticket = {"ticket_code": "HRCC-1", "urgency": "P1"}
        text = format_outcome(EscalationOutcome(lead_key="sreesanth", ticket=ticket, dm_delivered=True))
        assert "HRCC-1" in text and "dispatched" in text

    def test_duplicate(self) -> None:
        dup = {"ticket_code": "HRCC-9", "status": "PENDING", "poc_name": "sreesanth"}
        text = format_outcome(EscalationOutcome(lead_key="sreesanth", duplicate_of=dup))
        assert "HRCC-9" in text and "already" in text


class TestResolveLead:
    def test_by_name(self) -> None:
        assert resolve_lead("Sanskruti", "") == "sanskruti"

    def test_by_category(self) -> None:
        assert resolve_lead("", "tech") == "sreesanth"

    def test_invalid(self) -> None:
        assert resolve_lead("bob", "HR") is None


class TestExtractEscalationRequest:
    def test_finds_tool_call(self) -> None:
        msg = AIMessage(content="", tool_calls=[{
            "name": "create_escalation_ticket", "id": "c1",
            "args": {"category": "OPS", "urgency": "P1", "description": "rewards missing", "poc_name": "sanskruti"},
        }])
        req = extract_escalation_request({"messages": [msg]})
        assert req == {"lead_key": "sanskruti", "description": "rewards missing"}

    def test_ignores_other_tools_and_invalid_leads(self) -> None:
        msgs = [
            AIMessage(content="", tool_calls=[{"name": "calculate_reward_tier", "id": "c1", "args": {"participant_count": 5}}]),
            AIMessage(content="", tool_calls=[{"name": "create_escalation_ticket", "id": "c2", "args": {"poc_name": "bob", "category": "HR"}}]),
        ]
        assert extract_escalation_request({"messages": msgs}) is None

    def test_no_messages(self) -> None:
        assert extract_escalation_request({}) is None


class TestConfirmDispatchView:
    def test_other_users_cannot_confirm(self) -> None:
        from src.escalation_views import ConfirmDispatchView

        class _Resp:
            def __init__(self) -> None:
                self.messages: list[str] = []

            async def send_message(self, content: str, ephemeral: bool = False) -> None:
                self.messages.append(content)

        class _User:
            id = 99

        class _Interaction:
            user = _User()
            response = _Resp()

        async def run() -> tuple[bool, list[str]]:
            view = ConfirmDispatchView(
                requester_id=42, channel_id=1, message_id=2, lead_key="sreesanth", description="x",
            )
            inter = _Interaction()
            allowed = await view.interaction_check(inter)  # type: ignore[arg-type]
            return allowed, inter.response.messages

        allowed, messages = asyncio.run(run())
        assert allowed is False
        assert "Only the ambassador" in messages[0]
