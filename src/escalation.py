from __future__ import annotations

import logging
from typing import Any

import discord

from src.config import settings
from src.db import create_ticket, get_recent_tickets

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


def check_cooldown(author_id: int, category: str, urgency: str) -> bool:
    if urgency == "P0" and settings.enable_p0_override:
        return False
    recent = get_recent_tickets(
        author_id, category, hours=settings.escalation_cooldown_hours
    )
    return len(recent) > 0


async def dispatch_escalation(
    *,
    client: discord.Client,
    message: discord.Message,
    lead_key: str,
    description: str = "",
) -> dict[str, Any] | None:
    category = CATEGORY_MAP.get(lead_key, "OPS")
    urgency = _classify_urgency(description or message.content)

    if check_cooldown(message.author.id, category, urgency):
        await message.reply(
            f"You already have an active ticket for this category. "
            f"Please wait before opening another (cooldown: {settings.escalation_cooldown_hours}h).",
            mention_author=False,
        )
        return None

    poc_id = _get_poc_id(lead_key)

    ticket = create_ticket(
        channel_id=message.channel.id,
        message_id=message.id,
        author_id=message.author.id,
        author_name=str(message.author),
        category=category,
        urgency=urgency,
        poc_name=lead_key,
        poc_id=poc_id,
        description=description or message.content,
    )

    from src.db import log_audit
    log_audit(
        actor_id=message.author.id, actor_name=str(message.author),
        action="ESCALATE", details=f"{ticket['ticket_code']} {urgency} -> {lead_key}",
    )

    await message.reply(
        f"Ticket **{ticket['ticket_code']}** ({urgency}) dispatched to "
        f"**{POC_DISPLAY.get(lead_key, lead_key)}**. You will be notified upon review.",
        mention_author=False,
    )

    if poc_id and settings.enable_dm_routing:
        await _send_poc_dm(client, ticket)

    return ticket


async def _send_poc_dm(client: discord.Client, ticket: dict[str, Any]) -> None:
    poc_id_str = ticket["poc_id"]
    if not poc_id_str:
        return

    try:
        poc_user = await client.fetch_user(int(poc_id_str))
    except (discord.NotFound, discord.HTTPException, ValueError):
        log.warning("Could not fetch POC user %s for ticket %s", poc_id_str, ticket["ticket_code"])
        return

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

    from src.escalation_views import TicketActionView
    view = TicketActionView(ticket_code=ticket["ticket_code"])

    try:
        dm_channel = await poc_user.create_dm()
        await dm_channel.send(embed=embed, view=view)
        log.info("DM sent to %s for ticket %s", poc_user, ticket["ticket_code"])
    except discord.Forbidden:
        log.warning("Cannot DM %s (DMs disabled) for ticket %s", poc_user, ticket["ticket_code"])
    except discord.HTTPException:
        log.exception("Failed to DM %s for ticket %s", poc_user, ticket["ticket_code"])
