"""Slash commands, grouped by who may use them."""
from __future__ import annotations

from discord import app_commands

from hrcc_bot.bot.commands import admin, ambassador, community, moderation, owner, public
from hrcc_bot.bot.commands._common import QUIZ_QUESTIONS

__all__ = ["register_commands", "QUIZ_QUESTIONS"]


def register_commands(tree: app_commands.CommandTree) -> None:
    for module in (public, ambassador, community, moderation, admin, owner):
        module.register(tree)
