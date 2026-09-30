from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import discord

from hrcc_bot.config import settings
from hrcc_bot.core.db import create_ticket, get_recent_tickets

log = logging.getLogger("hrcc.escalation")

CATEGORY_MAP: dict[str, str] = {
    "sanskruti": "OPS",
    "sreesanth": "TECH",
    "nitish": "DESIGN",
}

POC_DISPLAY: dict[str, str] = {
    "sanskruti": "Sanskruti (Program Manager)",
    "sreesanth": "Sreesanth (Technical Lead)",
    "nitish": "Nitish (Design Lead)",
}


def _get_poc_id(lead_key: str) -> str:
    mapping = {
        "sanskruti": settings.poc_discord_sanskruti,
        "sreesanth": settings.poc_discord_sreesanth,
        "nitish": settings.poc_discord_nitish,
    }
    return mapping.get(lead_key, "")


def _classify_urgency(text: str) -> str:
    text_lower = text.lower()
    p0_signals = [
        "live right now", "contest is live", "event starts in",
        "500 error", "students getting error", "test link broken",
        "urgent", "emergency", "outage right now",
    ]
    for signal in p0_signals:
        if signal in text_lower:
            return "P0"

    p1_signals = [
        "winner spreadsheet", "activation missing", "reward not activated",
        "hrw invitation", "pending", "speaker confirmation",
        "not working", "login issue", "account locked",
    ]
    for signal in p1_signals:
        if signal in text_lower:
            return "P1"

    return "P2"


def resolve_lead(poc_name: str = "", category: str = "") -> str | None:
    """Map a lead name or ticket category to a lead key, or None if neither is valid."""
    key = (poc_name or "").strip().lower()
    if key in CATEGORY_MAP:
        return key
    cat = (category or "").strip().upper()
    for lead_key, lead_cat in CATEGORY_MAP.items():
        if lead_cat == cat:
            return lead_key
    return None


def find_open_duplicate(author_id: int, category: str, urgency: str) -> dict[str, Any] | None:
    """Return the ambassador's open ticket in this category from the cooldown window, if any.

    P0 emergencies bypass the cooldown when ``enable_p0_override`` is set.
    """
    if urgency == "P0" and settings.enable_p0_override:
        return None
    recent = get_recent_tickets(
        author_id, category, hours=settings.escalation_cooldown_hours
    )
    return recent[0] if recent else None


def check_cooldown(author_id: int, category: str, urgency: str) -> bool:
    return find_open_duplicate(author_id, category, urgency) is not None


@dataclass
class EscalationOutcome:
    lead_key: str
    ticket: dict[str, Any] | None = None
    duplicate_of: dict[str, Any] | None = None
    dm_delivered: bool = False


async def open_escalation(
    *,
    client: discord.Client,
    channel_id: int,
    message_id: int,
    author_id: int,
    author_name: str,
    lead_key: str,
    description: str,
    urgency: str | None = None,
) -> EscalationOutcome:
    """Create a ticket and DM the lead, enforcing the per-category cooldown.

    Shared by ``/escalate`` and chat-initiated escalations (after the
    ambassador clicks Confirm Dispatch).
    """
    category = CATEGORY_MAP.get(lead_key, "OPS")
    urgency = urgency or _classify_urgency(description)

    existing = find_open_duplicate(author_id, category, urgency)
    if existing:
        return EscalationOutcome(lead_key=lead_key, duplicate_of=existing)

    poc_id = _get_poc_id(lead_key)
    ticket = create_ticket(
        channel_id=channel_id,
        message_id=message_id,
        author_id=author_id,
        author_name=author_name,
        category=category,
        urgency=urgency,
        poc_name=lead_key,
        poc_id=poc_id,
        description=description,
    )

    from hrcc_bot.core.db import log_audit
    log_audit(
        actor_id=author_id, actor_name=author_name,
        action="ESCALATE", details=f"{ticket['ticket_code']} {urgency} -> {lead_key}",
    )

    delivered = False
    if poc_id and settings.enable_dm_routing:
        delivered = await _send_poc_dm(client, ticket)
    else:
        log.warning(
            "Ticket %s not DMed: POC id for %s is %s and DM routing is %s",
            ticket["ticket_code"], lead_key, "set" if poc_id else "unset",
            "on" if settings.enable_dm_routing else "off",
        )
    return EscalationOutcome(lead_key=lead_key, ticket=ticket, dm_delivered=delivered)


async def escalate_incident(
    *,
    client: discord.Client,
    report: Any,
    channel_id: int,
    message_id: int,
    author_id: int,
    author_name: str,
) -> EscalationOutcome:
    """Open a P0 ticket for the Technical Lead when an incident storm is detected."""
    samples = "\n".join(f"- {m[:200]}" for m in report.messages[-3:])
    description = (
        f"[Incident storm] {report.count} ambassadors reported the same error within minutes "
        f"across {len(report.channel_ids)} channel(s).\nSample reports:\n{samples}"
    )
    return await open_escalation(
        client=client,
        channel_id=channel_id,
        message_id=message_id,
        author_id=author_id,
        author_name=author_name,
        lead_key="sreesanth",
        description=description,
        urgency="P0",
    )


def incident_notice(report: Any, outcome: EscalationOutcome) -> str:
    """Channel message for a detected incident that only claims what actually happened."""
    if outcome.ticket and outcome.dm_delivered:
        status = f"**Sreesanth (Technical Lead)** has been notified (ticket **{outcome.ticket['ticket_code']}**)."
    elif outcome.ticket:
        status = f"A P0 ticket **{outcome.ticket['ticket_code']}** has been logged for **Sreesanth (Technical Lead)**."
    elif outcome.duplicate_of:
        status = f"This is being tracked under ticket **{outcome.duplicate_of['ticket_code']}**."
    else:
        status = "Please use `/escalate` to reach the Technical Lead."
    return (
        f"**Platform Incident Detected** — {report.count} reports in the last 2 minutes.\n"
        f"{status}\n"
        f"If HRW is down, use **HRC** (`hackerrank.com`) as a fallback."
    )


def format_outcome(outcome: EscalationOutcome) -> str:
    lead = POC_DISPLAY.get(outcome.lead_key, outcome.lead_key)
    if outcome.duplicate_of:
        dup = outcome.duplicate_of
        return (
            f"You already have an open ticket **{dup['ticket_code']}** ({dup['status']}) "
            f"with **{dup['poc_name'].title()}** for this category, so I haven't pinged them again. "
            f"Track it with `/ticket_status {dup['ticket_code']}`."
        )
    ticket = outcome.ticket or {}
    if outcome.dm_delivered:
        return (
            f"Ticket **{ticket['ticket_code']}** ({ticket['urgency']}) dispatched to **{lead}**. "
            f"You'll be notified here when they respond."
        )
    return (
        f"Ticket **{ticket['ticket_code']}** ({ticket['urgency']}) logged for **{lead}**. "
        f"I couldn't DM them directly, but it's in the leads' ticket queue."
    )


async def _send_poc_dm(client: discord.Client, ticket: dict[str, Any]) -> bool:
    poc_id_str = ticket["poc_id"]
    if not poc_id_str:
        return False

    try:
        poc_user = await client.fetch_user(int(poc_id_str))
    except (discord.NotFound, discord.HTTPException, ValueError):
        log.warning("Could not fetch POC user %s for ticket %s", poc_id_str, ticket["ticket_code"])
        return False

    urgency_label = {
        "P0": "P0 EMERGENCY",
        "P1": "P1 OPERATIONAL",
        "P2": "P2 GENERAL",
    }.get(ticket["urgency"], ticket["urgency"])

    color = {
        "P0": discord.Color.red(),
        "P1": discord.Color.orange(),
        "P2": discord.Color.blue(),
    }.get(ticket["urgency"], discord.Color.greyple())

    embed = discord.Embed(
        title=f"CAMPUS CREW TICKET {ticket['ticket_code']} — {urgency_label}",
        color=color,
        timestamp=discord.utils.utcnow(),
    )
    embed.add_field(name="Ambassador", value=ticket["author_name"], inline=True)
    embed.add_field(name="Category", value=ticket["category"], inline=True)
    embed.add_field(name="Status", value=ticket["status"], inline=True)
    embed.add_field(name="Issue", value=ticket["description"][:1024] or "No description", inline=False)
    embed.set_footer(text=f"Channel ID: {ticket['channel_id']} | Message ID: {ticket['message_id']}")

    from hrcc_bot.bot.escalation_views import TicketActionView
    view = TicketActionView(ticket_code=ticket["ticket_code"])

    try:
        dm_channel = await poc_user.create_dm()
        await dm_channel.send(embed=embed, view=view)
        log.info("DM sent to %s for ticket %s", poc_user, ticket["ticket_code"])
        return True
    except discord.Forbidden:
        log.warning("Cannot DM %s (DMs disabled) for ticket %s", poc_user, ticket["ticket_code"])
    except discord.HTTPException:
        log.exception("Failed to DM %s for ticket %s", poc_user, ticket["ticket_code"])
    return False
