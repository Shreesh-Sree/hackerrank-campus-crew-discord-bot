from __future__ import annotations

import logging
from dataclasses import dataclass

import httpx

log = logging.getLogger("hrcc.health")


@dataclass
class EngineProbe:
    name: str
    base_url: str
    model: str
    api_key: str = ""


@dataclass
class ProbeResult:
    ok: bool
    detail: str


async def probe_engine(client: httpx.AsyncClient, engine: EngineProbe) -> ProbeResult:
    """Check that an OpenAI-compatible endpoint is up AND serves the configured model.

    A reachable server with the wrong model is reported as down, since every
    completion against it would 404.
    """
    if not engine.base_url:
        return ProbeResult(False, "not configured")
    headers = {"Authorization": f"Bearer {engine.api_key}"} if engine.api_key else {}
    try:
        resp = await client.get(f"{engine.base_url.rstrip('/')}/models", headers=headers)
    except httpx.HTTPError as exc:
        return ProbeResult(False, f"unreachable ({type(exc).__name__})")
    if resp.status_code != 200:
        return ProbeResult(False, f"HTTP {resp.status_code}")
    try:
        served = [m.get("id", "") for m in resp.json().get("data", [])]
    except ValueError:
        return ProbeResult(False, "invalid /models response")
    if engine.model not in served:
        available = ", ".join(served[:5]) or "none"
        return ProbeResult(False, f"model '{engine.model}' not served (available: {available})")
    return ProbeResult(True, "ok")


class HealthMonitor:
    """Tracks engine health across probes and decides when to alert.

    Alerts fire once after ``failure_threshold`` consecutive probes with every
    engine down, and once more when any engine recovers.
    """

    def __init__(self, failure_threshold: int = 3) -> None:
        self.failure_threshold = max(1, failure_threshold)
        self.consecutive_outages = 0
        self.alerted = False
        self.last_status: dict[str, bool] = {}

    def changed_engines(self, results: dict[str, ProbeResult]) -> list[str]:
        """Engines whose up/down state differs from the previous probe."""
        changed = [
            name for name, res in results.items()
            if self.last_status.get(name) != res.ok
        ]
        self.last_status = {name: res.ok for name, res in results.items()}
        return changed

    def record(self, results: dict[str, ProbeResult]) -> str | None:
        """Return "down" or "recovered" when an alert should be sent, else None."""
        all_down = not any(r.ok for r in results.values())
        if all_down:
            self.consecutive_outages += 1
            if self.consecutive_outages >= self.failure_threshold and not self.alerted:
                self.alerted = True
                return "down"
            return None
        self.consecutive_outages = 0
        if self.alerted:
            self.alerted = False
            return "recovered"
        return None


def format_alert(kind: str, results: dict[str, ProbeResult], interval_s: int, threshold: int) -> str:
    lines = [f"- **{name}**: {res.detail}" for name, res in results.items()]
    if kind == "down":
        head = (
            f"**HRCC bot alert:** every inference engine has failed health checks for "
            f"~{interval_s * threshold // 60 or 1} min. Chat answers are failing; "
            f"slash commands that don't need the model still work."
        )
    else:
        head = "**HRCC bot recovered:** at least one inference engine is healthy again."
    return head + "\n" + "\n".join(lines)
