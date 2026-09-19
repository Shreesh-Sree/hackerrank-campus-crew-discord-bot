from __future__ import annotations

import logging
import re
import time
from collections import defaultdict
from dataclasses import dataclass, field

log = logging.getLogger("hrcc.incident")

WINDOW_SECONDS = 120
CLUSTER_THRESHOLD = 3

ERROR_SIGNATURES = [
    re.compile(r"(500|502|503|504)\s*(error|status)", re.IGNORECASE),
    re.compile(r"(hrw|hackerrank).{0,30}(not\s+(opening|working|loading)|down|timeout|outage)", re.IGNORECASE),
    re.compile(r"(test|contest|link).{0,20}(broken|404|error|not\s+found)", re.IGNORECASE),
    re.compile(r"(can'?t|cannot|unable).{0,20}(login|log\s*in|access|submit|open)", re.IGNORECASE),
    re.compile(r"(platform|server|site).{0,15}(down|crash|error|slow|lag)", re.IGNORECASE),
]


@dataclass
class IncidentReport:
    signature: str
    first_ts: float
    channel_ids: set[int] = field(default_factory=set)
    author_ids: set[int] = field(default_factory=set)
    messages: list[str] = field(default_factory=list)

    @property
    def count(self) -> int:
        return len(self.author_ids)


class IncidentClusterEngine:
    def __init__(self, window: int = WINDOW_SECONDS, threshold: int = CLUSTER_THRESHOLD) -> None:
        self._window = window
        self._threshold = threshold
        self._active: dict[str, IncidentReport] = {}

    def _match_signature(self, text: str) -> str | None:
        for pat in ERROR_SIGNATURES:
            m = pat.search(text)
            if m:
                return pat.pattern[:40]
        return None

    def _prune_stale(self) -> None:
        now = time.monotonic()
        stale = [k for k, v in self._active.items() if now - v.first_ts > self._window * 3]
        for k in stale:
            del self._active[k]

    def ingest(self, text: str, author_id: int, channel_id: int) -> IncidentReport | None:
        self._prune_stale()

        sig = self._match_signature(text)
        if not sig:
            return None

        now = time.monotonic()

        if sig not in self._active:
            self._active[sig] = IncidentReport(
                signature=sig, first_ts=now,
            )

        report = self._active[sig]

        if now - report.first_ts > self._window and report.count < self._threshold:
            report = IncidentReport(signature=sig, first_ts=now)
            self._active[sig] = report

        report.author_ids.add(author_id)
        report.channel_ids.add(channel_id)
        report.messages.append(text[:200])

        if report.count == self._threshold:
            log.info(
                "Incident cluster detected: sig=%s, reports=%d, channels=%d",
                sig[:30], report.count, len(report.channel_ids),
            )
            return report

        if report.count > self._threshold:
            return report

        return None

    def resolve(self, signature: str) -> IncidentReport | None:
        return self._active.pop(signature, None)

    def get_active_incidents(self) -> list[IncidentReport]:
        self._prune_stale()
        return [r for r in self._active.values() if r.count >= self._threshold]


incident_engine = IncidentClusterEngine()
