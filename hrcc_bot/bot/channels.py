from __future__ import annotations

from enum import Enum

from hrcc_bot.config import settings


class ChannelMode(str, Enum):
    PROACTIVE = "proactive"          # answer relevant questions without a mention
    MENTION_ONLY = "mention_only"    # stay silent unless the bot is tagged
    BROADCAST_ONLY = "broadcast_only"  # ignore all chat; leads post via /support_broadcast


def parse_channel_ids(raw: str) -> set[int]:
    ids: set[int] = set()
    for part in (raw or "").replace(" ", "").split(","):
        if part.isdigit():
            ids.add(int(part))
    return ids


def support_channel_ids() -> set[int]:
    return parse_channel_ids(settings.support_channel_ids)


def announcement_channel_ids() -> set[int]:
    return parse_channel_ids(settings.announcement_channel_ids)


def get_channel_mode(channel_id: int, parent_id: int | None = None) -> ChannelMode:
    """Resolve how the bot behaves in a channel (threads inherit their parent's mode).

    With no SUPPORT_CHANNEL_IDS configured every channel is proactive, which
    preserves the original behaviour.
    """
    ids = {channel_id} | ({parent_id} if parent_id else set())
    if ids & announcement_channel_ids():
        return ChannelMode.BROADCAST_ONLY
    support = support_channel_ids()
    if not support or ids & support:
        return ChannelMode.PROACTIVE
    return ChannelMode.MENTION_ONLY
