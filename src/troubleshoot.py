from __future__ import annotations

import logging
from dataclasses import dataclass, field

import discord
from discord import ui

log = logging.getLogger("hrcc.troubleshoot")


@dataclass(frozen=True)
class Node:
    title: str
    text: str
    options: list[tuple[str, str]] = field(default_factory=list)  # (button label, next node id)
    escalate_to: str | None = None  # lead key offered as a one-click ticket
    ticket_summary: str = ""        # issue text used for the ticket (drives P0/P1/P2)


# Decision trees grounded in references/troubleshooting_and_faqs.md and the
# handbook's Troubleshooting Manual. Edit wording here, not in the view code.
NODES: dict[str, Node] = {
    "root": Node(
        title="HackerRank Self-Service Troubleshooting",
        text="Select the issue you are experiencing:",
        options=[
            ("HRW Account Activation Pending", "hrw_activation"),
            ("Contest Closed / Buffer Time Issue", "contest_closed"),
            ("Winner Reward Activation Delayed", "reward_delayed"),
            ("College Name Not Listed in Dropdown", "college_missing"),
            ("Live Platform Outage / Compiler Error", "live_outage"),
        ],
    ),
    # ── HRW activation ────────────────────────────────────────────────────
    "hrw_activation": Node(
        title="HRW Activation Pending — Step 1",
        text=(
            "Did you check **both inbox and spam/promotions** for the email you applied with "
            "(including any college-issued address) for the HRW recruiter invite?"
        ),
        options=[("Found it!", "solved"), ("Yes, still not found", "hrw_activation_timing")],
    ),
    "hrw_activation_timing": Node(
        title="HRW Activation Pending — Step 2",
        text="Is your event scheduled within the next **48 hours**?",
        options=[("Yes, event is soon", "hrw_activation_soon"), ("No, it's later", "hrw_activation_later")],
    ),
    "hrw_activation_soon": Node(
        title="Use HRC for this event",
        text=(
            "Host this event on **HRC** (`hackerrank.com`) so your schedule isn't delayed — "
            "HRC is the approved fallback while HRW access is pending.\n\n"
            "Want the Technical Lead to chase your HRW activation?"
        ),
        escalate_to="sreesanth",
        ticket_summary="HRW activation email never arrived (checked spam); event within 48 hours, using HRC meanwhile.",
    ),
    "hrw_activation_later": Node(
        title="Likely queued for the next onboarding batch",
        text=(
            "Your account is probably in an upcoming **onboarding batch**. You can still use **HRC** "
            "in the meantime if you need to start preparing.\n\n"
            "If it genuinely never arrives, log a ticket with the Technical Lead."
        ),
        escalate_to="sreesanth",
        ticket_summary="HRW activation email not received (checked spam); event not within 48 hours.",
    ),
    # ── Contest closed ────────────────────────────────────────────────────
    "contest_closed": Node(
        title="Contest Closed / Buffer Time",
        text="Has the contest already reached its **scheduled end time**?",
        options=[("Yes, it's closed", "contest_closed_final"), ("No — students can't get in right now", "live_outage")],
    ),
    "contest_closed_final": Node(
        title="Closed contests cannot be reopened",
        text=(
            "Closed contests are **not reopened under any circumstance** — the end time is a hard cutoff.\n\n"
            "For future events:\n"
            "- Configure a **15–30 minute buffer** after the planned end time.\n"
            "- Communicate the closing time clearly in advance.\n"
            "- Report access issues **in real time** while the event is live.\n\n"
            "Everyone who submitted code/answers is still eligible for a participation certificate."
        ),
    ),
    # ── Reward activation ─────────────────────────────────────────────────
    "reward_delayed": Node(
        title="Winner Reward Delayed — Step 1",
        text="How long ago did you submit the winner details to the Program Manager?",
        options=[("Under 48 hours", "reward_wait"), ("Over 48 hours", "reward_email_check")],
    ),
    "reward_wait": Node(
        title="Activation is still in progress",
        text=(
            "Activation happens directly on winner accounts and usually takes **24–48 hours**. "
            "Ask the winner to check their HackerRank profile and email again after that window."
        ),
    ),
    "reward_email_check": Node(
        title="Winner Reward Delayed — Step 2",
        text=(
            "Did you confirm the submitted email **exactly matches the email on the winner's HackerRank "
            "account**? Mismatched (e.g. roll-number) emails are the most common cause of failed activation."
        ),
        options=[("Yes, emails match", "reward_escalate"), ("Not sure", "reward_fix_email")],
    ),
    "reward_fix_email": Node(
        title="Confirm the winner's HackerRank email",
        text=(
            "Check the address with `/verify_emails`, then resubmit **that specific winner's** details "
            "to the Program Manager. If it still fails after resubmitting, raise a ticket."
        ),
        escalate_to="sanskruti",
        ticket_summary="Winner reward not activated after 48h; email match unconfirmed, resubmitting winner details.",
    ),
    "reward_escalate": Node(
        title="Follow up with the Program Manager",
        text="Emails match and it's been over 48 hours — follow up with the Program Manager with that winner's details.",
        escalate_to="sanskruti",
        ticket_summary="Winner reward activation missing after 48h; submitted email matches HackerRank account.",
    ),
    # ── College dropdown ──────────────────────────────────────────────────
    "college_missing": Node(
        title="College not listed",
        text="Select **\"Other\"** in the dropdown and type your college's **official name** manually.",
    ),
    # ── Live outage ───────────────────────────────────────────────────────
    "live_outage": Node(
        title="Platform Outage / Compiler Error",
        text="Is your event **live right now**?",
        options=[("Yes, it's live", "live_outage_now"), ("No, not started yet", "live_outage_prep")],
    ),
    "live_outage_now": Node(
        title="Report it now — speed matters",
        text=(
            "- Keep the **exact contest URL** and a screenshot of the error.\n"
            "- If **HRW** is down, move participants to **HRC** (`hackerrank.com`) as the fallback.\n"
            "- Never use the **Chakra** tab or SkillUp to work around it.\n\n"
            "Escalate to the Technical Lead immediately:"
        ),
        escalate_to="sreesanth",
        ticket_summary="Contest is live right now and students getting error on the platform (outage/compiler error).",
    ),
    "live_outage_prep": Node(
        title="Check the link before the event",
        text=(
            "Confirm the shared link matches **exactly** what's on your admin dashboard, and that the "
            "contest window has started. You can also run `/event_check` on the URL.\n\n"
            "If it still errors, log a ticket with the Technical Lead."
        ),
        escalate_to="sreesanth",
        ticket_summary="Contest link returns an error before the event (link verified against dashboard).",
    ),
    "solved": Node(title="Glad that's sorted!", text="Run `/troubleshoot` again any time."),
}


def build_embed(node: Node) -> discord.Embed:
    return discord.Embed(title=node.title, description=node.text, color=discord.Color.blurple())


class _OptionButton(ui.Button["TroubleshootView"]):
    def __init__(self, label: str, next_id: str) -> None:
        super().__init__(label=label[:80], style=discord.ButtonStyle.primary)
        self.next_id = next_id

    async def callback(self, interaction: discord.Interaction) -> None:
        assert self.view is not None
        self.view.path.append(self.label or "")
        await self.view.show(interaction, self.next_id)


class _EscalateButton(ui.Button["TroubleshootView"]):
    def __init__(self, lead_key: str) -> None:
        from src.escalation import POC_DISPLAY

        super().__init__(label=f"Escalate to {POC_DISPLAY.get(lead_key, lead_key)}"[:80], style=discord.ButtonStyle.danger)
        self.lead_key = lead_key

    async def callback(self, interaction: discord.Interaction) -> None:
        from src.escalation import format_outcome, open_escalation

        assert self.view is not None
        node = NODES[self.view.node_id]
        self.view.clear_items()
        await interaction.response.edit_message(view=self.view)
        self.view.stop()

        description = f"[Troubleshooter] {node.ticket_summary} Path: {' > '.join(self.view.path)}"
        outcome = await open_escalation(
            client=interaction.client,
            channel_id=interaction.channel_id or 0,
            message_id=0,
            author_id=interaction.user.id,
            author_name=str(interaction.user),
            lead_key=self.lead_key,
            description=description,
        )
        await interaction.followup.send(format_outcome(outcome), ephemeral=True)


class TroubleshootView(ui.View):
    def __init__(self, requester_id: int, node_id: str = "root") -> None:
        super().__init__(timeout=600)
        self.requester_id = requester_id
        self.path: list[str] = []
        self.node_id = node_id
        self._render(node_id)

    def _render(self, node_id: str) -> None:
        self.node_id = node_id
        node = NODES[node_id]
        self.clear_items()
        for label, next_id in node.options:
            self.add_item(_OptionButton(label, next_id))
        if node.escalate_to:
            self.add_item(_EscalateButton(node.escalate_to))

    async def show(self, interaction: discord.Interaction, node_id: str) -> None:
        self._render(node_id)
        await interaction.response.edit_message(embed=build_embed(NODES[node_id]), view=self)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.requester_id:
            await interaction.response.send_message("Run `/troubleshoot` to start your own session.", ephemeral=True)
            return False
        return True
