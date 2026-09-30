from __future__ import annotations

import asyncio
import os

os.environ.setdefault("DISCORD_BOT_TOKEN", "test-token")

from hrcc_bot.services.escalation import CATEGORY_MAP, _classify_urgency
from hrcc_bot.bot.troubleshoot import NODES, TroubleshootView


def _reachable(start: str = "root") -> set[str]:
    seen: set[str] = set()
    stack = [start]
    while stack:
        node_id = stack.pop()
        if node_id in seen:
            continue
        seen.add(node_id)
        stack.extend(next_id for _, next_id in NODES[node_id].options)
    return seen


class TestTreeIntegrity:
    def test_all_targets_exist(self) -> None:
        for node_id, node in NODES.items():
            for label, next_id in node.options:
                assert next_id in NODES, f"{node_id} -> {label} -> missing {next_id}"

    def test_every_node_reachable(self) -> None:
        assert _reachable() == set(NODES)

    def test_five_root_issues(self) -> None:
        assert len(NODES["root"].options) == 5

    def test_escalations_valid_and_summarised(self) -> None:
        for node_id, node in NODES.items():
            if node.escalate_to:
                assert node.escalate_to in CATEGORY_MAP, node_id
                assert node.ticket_summary, node_id

    def test_button_labels_fit_discord_limit(self) -> None:
        for node in NODES.values():
            for label, _ in node.options:
                assert len(label) <= 80

    def test_live_outage_ticket_is_p0(self) -> None:
        assert _classify_urgency(NODES["live_outage_now"].ticket_summary) == "P0"

    def test_hrw_leaf_escalates_to_tech_lead(self) -> None:
        assert NODES["hrw_activation_soon"].escalate_to == "sreesanth"


class TestTroubleshootView:
    def test_root_renders_one_button_per_issue(self) -> None:
        async def run() -> int:
            return len(TroubleshootView(requester_id=1).children)
        assert asyncio.run(run()) == 5

    def test_leaf_with_escalation_renders_escalate_button(self) -> None:
        async def run() -> list[str]:
            view = TroubleshootView(requester_id=1, node_id="live_outage_now")
            return [getattr(c, "label", "") for c in view.children]
        labels = asyncio.run(run())
        assert labels == ["Escalate to Sreesanth (Technical Lead)"]
