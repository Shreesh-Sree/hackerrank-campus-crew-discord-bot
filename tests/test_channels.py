from __future__ import annotations

import os

import pytest

os.environ.setdefault("DISCORD_BOT_TOKEN", "test-token")

from src.channels import ChannelMode, get_channel_mode, parse_channel_ids
from src.config import settings


class TestParseChannelIds:
    def test_parses_and_ignores_junk(self) -> None:
        assert parse_channel_ids(" 1, 2,abc,,3 ") == {1, 2, 3}

    def test_empty(self) -> None:
        assert parse_channel_ids("") == set()


class TestChannelMode:
    def test_unconfigured_is_proactive_everywhere(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(settings, "support_channel_ids", "")
        monkeypatch.setattr(settings, "announcement_channel_ids", "")
        assert get_channel_mode(123) is ChannelMode.PROACTIVE

    def test_support_vs_other_channels(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(settings, "support_channel_ids", "10,11")
        monkeypatch.setattr(settings, "announcement_channel_ids", "")
        assert get_channel_mode(10) is ChannelMode.PROACTIVE
        assert get_channel_mode(99) is ChannelMode.MENTION_ONLY

    def test_announcements_ignore_chat(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(settings, "support_channel_ids", "")
        monkeypatch.setattr(settings, "announcement_channel_ids", "50")
        assert get_channel_mode(50) is ChannelMode.BROADCAST_ONLY

    def test_threads_inherit_parent_mode(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(settings, "support_channel_ids", "10")
        monkeypatch.setattr(settings, "announcement_channel_ids", "50")
        assert get_channel_mode(777, parent_id=10) is ChannelMode.PROACTIVE
        assert get_channel_mode(778, parent_id=50) is ChannelMode.BROADCAST_ONLY
