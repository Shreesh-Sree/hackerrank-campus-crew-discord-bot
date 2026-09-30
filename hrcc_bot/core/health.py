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


class DbMonitor:
    """Decides when to alert about the database backend (one alert per state change)."""

    ALERT_STATES = {"failover", "postgres_back"}

    def __init__(self) -> None:
        self.state: str | None = None

    def evaluate(self, *, configured_postgres: bool, active: str, postgres_reachable: bool | None) -> str | None:
        if not configured_postgres or active == "postgres":
            state = "ok"
        elif postgres_reachable:
            state = "postgres_back"
        else:
            state = "failover"
        previous, self.state = self.state, state
        if state == previous:
            return None
        if state in self.ALERT_STATES:
            return state
        return None


def format_db_alert(state: str, since: str | None) -> str:
    since_txt = f" since {since[:19].replace('T', ' ')} UTC" if since else ""
    if state == "failover":
        return (
            f"**HRCC bot alert:** PostgreSQL is unreachable, so the bot is running on its SQLite fallback{since_txt}. "
            "Everything still works; new data is stored only in SQLite until it is migrated."
        )
    return (
        f"**HRCC bot:** PostgreSQL is reachable again, but the bot stays on SQLite because it holds writes "
        f"made{since_txt} that Postgres doesn't have. To switch back without losing them, run "
        "`python -m hrcc_bot.core.migrate_to_postgres --dry-run`, then without `--dry-run`, then restart the bot."
    )
