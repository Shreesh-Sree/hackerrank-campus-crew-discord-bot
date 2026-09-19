from __future__ import annotations

import functools
import logging
from enum import IntEnum
from typing import Any, Callable, Coroutine

import discord
from discord import app_commands

from src.config import settings
from src.db import get_hrw_link, is_moderator

log = logging.getLogger("hrcc.auth")


class Role(IntEnum):
    UNREGISTERED = 0
    AMBASSADOR = 10
    MODERATOR = 20
    ADMIN = 30
    OWNER = 40


def _admin_ids() -> set[int]:
    ids: set[int] = set()
    for val in (settings.poc_discord_sanskruti, settings.poc_discord_sreesanth, settings.poc_discord_nitish):
        if val:
            try:
                ids.add(int(val))
            except ValueError:
                pass
    return ids


def _owner_id() -> int | None:
    if settings.owner_discord_id:
        try:
            return int(settings.owner_discord_id)
        except ValueError:
            pass
    return None


def get_user_role(user_id: int) -> Role:
    owner = _owner_id()
    if owner and user_id == owner:
        return Role.OWNER

    if user_id in _admin_ids():
        return Role.ADMIN

    if is_moderator(user_id):
        return Role.MODERATOR

    if get_hrw_link(user_id):
        return Role.AMBASSADOR

    return Role.UNREGISTERED


ROLE_LABELS = {
    Role.UNREGISTERED: "Unregistered",
    Role.AMBASSADOR: "Ambassador",
    Role.MODERATOR: "Moderator",
    Role.ADMIN: "Admin",
    Role.OWNER: "Owner",
}

UNGATED_COMMANDS = {
    "register", "rules", "sop", "resources", "rewards",
    "onboard", "certs", "question_bank",
}

PRIVACY_EPHEMERAL = {
    "register", "my_status", "my_tests", "test_status", "set_profile",
    "set_stage", "benchmark", "onboard_quiz", "event_check", "create_event",
    "curate_contest", "escalate", "ticket_status", "verify_emails",
    "submit_report", "find_ambassador", "collab_request", "admin_stats",
    "ambassador", "admin_points", "admin_broadcast", "admin_set_mod",
    "admin_revoke", "admin_export", "admin_tickets", "mod_lookup",
    "mod_tickets", "mod_activity", "mod_verify", "owner_api_status",
    "owner_config", "owner_sync_users", "link_hrw",
}


def is_ephemeral_command(name: str) -> bool:
    return name in PRIVACY_EPHEMERAL


def require_role(min_role: Role):
    def decorator(func: Callable[..., Coroutine[Any, Any, Any]]):
        @functools.wraps(func)
        async def wrapper(interaction: discord.Interaction, *args: Any, **kwargs: Any) -> Any:
            user_role = get_user_role(interaction.user.id)
            if user_role < min_role:
                if user_role == Role.UNREGISTERED and min_role <= Role.AMBASSADOR:
                    msg = "You need to register first. Run `/register` to verify your HRW identity."
                else:
                    msg = f"This command requires **{ROLE_LABELS[min_role]}** access or higher."
                await interaction.response.send_message(msg, ephemeral=True)
                return
            return await func(interaction, *args, **kwargs)
        return wrapper
    return decorator


def check_gate(user_id: int, command_name: str) -> str | None:
    if command_name in UNGATED_COMMANDS:
        return None

    role = get_user_role(user_id)
    if role >= Role.AMBASSADOR:
        return None

    return "You need to register first. Run `/register` to verify your HRW identity."
