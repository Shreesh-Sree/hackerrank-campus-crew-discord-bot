from __future__ import annotations

import asyncio
import inspect
from pathlib import Path
from typing import Any

import discord
import pytest

from hrcc_bot.bot.auth_gate import UNGATED_COMMANDS, GatedCommandTree
from hrcc_bot.bot.commands import admin, ambassador, community, moderation, owner, public
from hrcc_bot.config import settings
from hrcc_bot.core import db as db_mod
from hrcc_bot.core.db import close_db, create_ticket, init_db

MODULES = {"public": public, "ambassador": ambassador, "community": community,
           "moderation": moderation, "admin": admin, "owner": owner}


def _tree_for(*modules: Any) -> GatedCommandTree:
    tree = GatedCommandTree(discord.Client(intents=discord.Intents.default()))
    for m in modules:
        m.register(tree)
    return tree


def _names(module: Any) -> set[str]:
    async def run() -> set[str]:
        return {c.name for c in _tree_for(module).get_commands()}
    return asyncio.run(run())


@pytest.fixture(autouse=True)
def _use_temp_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(db_mod, "_SQLITE_PATH", tmp_path / "test.db")
    monkeypatch.setattr(db_mod, "_using_postgres", False)
    db_mod._local.sqlite_conn = None  # type: ignore[attr-defined]
    init_db()
    yield
    close_db()


class TestRegistry:
    def test_every_command_registered_once(self) -> None:
        per_module = {k: _names(m) for k, m in MODULES.items()}
        all_names = [n for names in per_module.values() for n in names]
        assert len(all_names) == len(set(all_names)) == 56

    def test_public_module_matches_ungated_list(self) -> None:
        assert _names(public) == UNGATED_COMMANDS

    @pytest.mark.parametrize("module_key", ["moderation", "admin", "owner"])
    def test_privileged_commands_check_role(self, module_key: str) -> None:
        """Every lead/mod/owner command must check the caller's role itself."""
        async def run() -> list[str]:
            tree = _tree_for(MODULES[module_key])
            return [
                c.name for c in tree.get_commands()
                if not any(tok in inspect.getsource(c.callback) for tok in ("get_user_role", "LEAD_IDS"))
            ]
        assert asyncio.run(run()) == []


class _Response:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def send_message(self, content: str | None = None, **kwargs: Any) -> None:
        self.calls.append({"content": content, **kwargs})

    async def defer(self, **kwargs: Any) -> None:
        pass


class _User:
    def __init__(self, uid: int) -> None:
        self.id = uid
        self.display_name = f"user{uid}"

    def __str__(self) -> str:
        return self.display_name


class _Interaction:
    def __init__(self, uid: int) -> None:
        self.user = _User(uid)
        self.response = _Response()


def _call(module: Any, name: str, interaction: _Interaction, **kwargs: Any) -> None:
    async def run() -> None:
        cmd = _tree_for(module).get_command(name)
        await cmd.callback(interaction, **kwargs)  # type: ignore[union-attr]
    asyncio.run(run())


class TestTicketStatusPrivacy:
    def _ticket(self) -> str:
        return create_ticket(channel_id=1, message_id=1, author_id=100, author_name="owner",
                             category="OPS", urgency="P2", poc_name="sanskruti", description="secret details")["ticket_code"]

    def test_owner_sees_own_ticket_privately(self) -> None:
        code = self._ticket()
        inter = _Interaction(100)
        _call(ambassador, "ticket_status", inter, ticket_code=code)
        call = inter.response.calls[0]
        assert call["ephemeral"] is True
        assert "secret details" in str(call["embed"].to_dict())

    def test_other_user_gets_not_found(self) -> None:
        code = self._ticket()
        inter = _Interaction(200)
        _call(ambassador, "ticket_status", inter, ticket_code=code)
        embed = inter.response.calls[0]["embed"].to_dict()
        assert embed["title"] == "Ticket Not Found"
        assert "secret details" not in str(embed)


class TestAmbassadorLookup:
    def test_requires_admin(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(settings, "owner_discord_id", "")
        monkeypatch.setattr(settings, "poc_discord_sanskruti", "")
        monkeypatch.setattr(settings, "poc_discord_sreesanth", "")
        monkeypatch.setattr(settings, "poc_discord_nitish", "")
        inter = _Interaction(300)
        _call(admin, "ambassador", inter, user=_User(301))
        assert inter.response.calls[0]["content"] == "Admin access required."
        assert inter.response.calls[0]["ephemeral"] is True

    def test_admin_gets_ephemeral_profile(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(settings, "poc_discord_sanskruti", "300")
        inter = _Interaction(300)
        _call(admin, "ambassador", inter, user=_User(301))
        call = inter.response.calls[0]
        assert call["ephemeral"] is True and "embed" in call
