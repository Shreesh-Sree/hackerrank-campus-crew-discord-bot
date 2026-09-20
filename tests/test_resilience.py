from __future__ import annotations

import asyncio
import os

import httpx
import pytest

os.environ.setdefault("DISCORD_BOT_TOKEN", "test-token")


# ── LLM failover proxy ────────────────────────────────────────────────────


class FakeEngine:
    def __init__(self, exc: Exception | None = None, value: str = "ok") -> None:
        self._exc = exc
        self._value = value

    async def ainvoke(self, *args: object, **kwargs: object) -> str:
        if self._exc is not None:
            raise self._exc
        return self._value


class TestLLMFailover:
    def test_fallback_used_on_connect_error(self) -> None:
        from src.llm_client import ResilientChatModel

        model = ResilientChatModel(
            FakeEngine(httpx.ConnectError("down")), FakeEngine(value="fallback-ok")
        )

        async def _run() -> str:
            return await model.ainvoke("hi")

        assert asyncio.run(_run()) == "fallback-ok"

    def test_fallback_used_on_timeout(self) -> None:
        from src.llm_client import ResilientChatModel

        model = ResilientChatModel(
            FakeEngine(httpx.TimeoutException("slow")), FakeEngine(value="fb")
        )

        async def _run() -> str:
            return await model.ainvoke("hi")

        assert asyncio.run(_run()) == "fb"

    def test_dual_failure_raises(self) -> None:
        from src.llm_client import LLMFailoverError, ResilientChatModel

        model = ResilientChatModel(
            FakeEngine(httpx.ConnectError("down")), FakeEngine(httpx.ConnectError("also down"))
        )

        async def _run() -> None:
            await model.ainvoke("hi")

        with pytest.raises(LLMFailoverError):
            asyncio.run(_run())

    def test_programming_error_propagates(self) -> None:
        from src.llm_client import ResilientChatModel

        model = ResilientChatModel(FakeEngine(TypeError("bug")), FakeEngine(value="fb"))

        async def _run() -> None:
            await model.ainvoke("hi")

        with pytest.raises(TypeError):
            asyncio.run(_run())

    def test_no_fallback_configured(self) -> None:
        from src.llm_client import ResilientChatModel

        model = ResilientChatModel(FakeEngine(httpx.ConnectError("down")), None)

        async def _run() -> None:
            await model.ainvoke("hi")

        with pytest.raises(httpx.ConnectError):
            asyncio.run(_run())


# ── Vision triage classification ──────────────────────────────────────────


class TestVisionTriage:
    def test_chakra_p0_banner(self) -> None:
        from src.vision import _classify_triage

        out = _classify_triage("The screenshot shows the Chakra tab open.")
        assert "P0 SECURITY TRIGGER" in out
        assert "CHAKRA TAB DETECTED" in out

    def test_404_banner(self) -> None:
        from src.vision import _classify_triage

        out = _classify_triage("HRW returned Error 404 — page not found.")
        assert "HRW TEST 404" in out

    def test_inactive_contest_banner(self) -> None:
        from src.vision import _classify_triage

        out = _classify_triage("The contest is inactive and no longer active.")
        assert "INACTIVE CONTEST" in out

    def test_proctoring_banner(self) -> None:
        from src.vision import _classify_triage

        out = _classify_triage("Candidate was disqualified for a proctoring violation.")
        assert "PROCTORING VIOLATION" in out

    def test_clean_analysis_unchanged(self) -> None:
        from src.vision import _classify_triage

        text = "Everything looks fine, the contest is running normally."
        assert _classify_triage(text) == text


# ── Vision endpoint chain ─────────────────────────────────────────────────


class TestVisionEndpoints:
    def test_empty_when_nothing_configured(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from src.config import settings
        from src.vision import _vision_endpoints

        monkeypatch.setattr(settings, "vision_base_url", "")
        monkeypatch.setattr(settings, "enable_nim_fallback", False)
        monkeypatch.setattr(settings, "ollama_base_url", "")
        monkeypatch.setattr(settings, "vllm_base_url", "")
        assert _vision_endpoints() == []

    def test_dedicated_first_then_fallbacks(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from src.config import settings
        from src.vision import _vision_endpoints

        monkeypatch.setattr(settings, "vision_base_url", "http://dedicated/v1")
        monkeypatch.setattr(settings, "vision_model", "ded-model")
        monkeypatch.setattr(settings, "enable_nim_fallback", True)
        monkeypatch.setattr(settings, "nim_base_url", "http://nim/v1")
        monkeypatch.setattr(settings, "ollama_base_url", "http://ollama/v1")

        chain = [e["label"] for e in _vision_endpoints()]
        assert chain[0] == "dedicated-vision"
        assert "nvidia-nim-vision" in chain
        assert "ollama-vision" in chain
        assert chain.index("dedicated-vision") < chain.index("ollama-vision")

    def test_nim_disabled_excludes_nim(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from src.config import settings
        from src.vision import _vision_endpoints

        monkeypatch.setattr(settings, "vision_base_url", "")
        monkeypatch.setattr(settings, "enable_nim_fallback", False)
        monkeypatch.setattr(settings, "ollama_base_url", "http://ollama/v1")
        chain = [e["label"] for e in _vision_endpoints()]
        assert chain == ["ollama-vision"]


# ── Contest reminder dedup ledger ─────────────────────────────────────────


class TestContestReminderDedup:
    def test_sends_once_per_stage(self) -> None:
        import src.scheduler as sched

        key_id, name = 99901, "dedup-test-event"
        assert sched._should_send(key_id, name, "T-24h") is True
        assert sched._should_send(key_id, name, "T-24h") is False
        # other stages for the same event still fire
        assert sched._should_send(key_id, name, "T-1h") is True

    def test_ledger_capped(self) -> None:
        import src.scheduler as sched

        for i in range(sched._REMINDER_LEDGER_CAP + 50):
            sched._should_send(i, f"ev-{i}", "T-24h")
        assert len(sched._sent_reminders) <= sched._REMINDER_LEDGER_CAP
