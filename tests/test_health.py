from __future__ import annotations

import asyncio
import os

import httpx

os.environ.setdefault("DISCORD_BOT_TOKEN", "test-token")

from src.health import EngineProbe, HealthMonitor, ProbeResult, format_alert, probe_engine


def _probe(handler, engine: EngineProbe) -> ProbeResult:
    async def run() -> ProbeResult:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await probe_engine(client, engine)
    return asyncio.run(run())


ENGINE = EngineProbe("vLLM", "http://engine/v1", "llama-8b", "key")


class TestProbeEngine:
    def test_healthy_when_model_served(self) -> None:
        seen: dict[str, str] = {}

        def handler(req: httpx.Request) -> httpx.Response:
            seen["url"] = str(req.url)
            seen["auth"] = req.headers.get("authorization", "")
            return httpx.Response(200, json={"data": [{"id": "llama-8b"}]})

        res = _probe(handler, ENGINE)
        assert res.ok
        assert seen["url"] == "http://engine/v1/models"
        assert seen["auth"] == "Bearer key"

    def test_wrong_model_is_down(self) -> None:
        res = _probe(lambda r: httpx.Response(200, json={"data": [{"id": "deepseek-r1:7b"}]}), ENGINE)
        assert not res.ok
        assert "llama-8b" in res.detail and "deepseek-r1:7b" in res.detail

    def test_http_error_is_down(self) -> None:
        res = _probe(lambda r: httpx.Response(401, json={}), ENGINE)
        assert not res.ok and "401" in res.detail

    def test_unreachable_is_down(self) -> None:
        def handler(req: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("refused", request=req)

        res = _probe(handler, ENGINE)
        assert not res.ok and "unreachable" in res.detail

    def test_unconfigured(self) -> None:
        res = _probe(lambda r: httpx.Response(200), EngineProbe("x", "", "m"))
        assert not res.ok and res.detail == "not configured"


UP = ProbeResult(True, "ok")
DOWN = ProbeResult(False, "unreachable")


class TestHealthMonitor:
    def test_alerts_once_after_threshold(self) -> None:
        mon = HealthMonitor(failure_threshold=3)
        outcomes = [mon.record({"a": DOWN, "b": DOWN}) for _ in range(5)]
        assert outcomes == [None, None, "down", None, None]

    def test_one_engine_up_is_not_outage(self) -> None:
        mon = HealthMonitor(failure_threshold=1)
        assert mon.record({"a": DOWN, "b": UP}) is None

    def test_recovery_alert_after_outage(self) -> None:
        mon = HealthMonitor(failure_threshold=1)
        assert mon.record({"a": DOWN}) == "down"
        assert mon.record({"a": UP}) == "recovered"
        assert mon.record({"a": UP}) is None

    def test_no_recovery_alert_without_prior_alert(self) -> None:
        mon = HealthMonitor(failure_threshold=3)
        mon.record({"a": DOWN})
        assert mon.record({"a": UP}) is None

    def test_changed_engines_reports_transitions_only(self) -> None:
        mon = HealthMonitor()
        assert mon.changed_engines({"a": UP, "b": DOWN}) == ["a", "b"]
        assert mon.changed_engines({"a": UP, "b": DOWN}) == []
        assert mon.changed_engines({"a": DOWN, "b": DOWN}) == ["a"]


class TestFormatAlert:
    def test_down_lists_each_engine(self) -> None:
        text = format_alert("down", {"vLLM": DOWN, "Fallback": ProbeResult(False, "model 'x' not served")}, 60, 3)
        assert "3 min" in text
        assert "vLLM" in text and "model 'x' not served" in text

    def test_recovered(self) -> None:
        assert "recovered" in format_alert("recovered", {"vLLM": UP}, 60, 3)
