from __future__ import annotations

import logging

import discord
from discord import ui

from src.db import get_ticket, update_ticket_status

log = logging.getLogger("hrcc.escalation_views")


class ResolveModal(ui.Modal, title="Resolve Ticket"):
    resolution = ui.TextInput(
        label="Resolution Notes",
        style=discord.TextStyle.paragraph,
        placeholder="Describe the resolution...",
        required=True,
        max_length=1000,
    )

    def __init__(self, ticket_code: str) -> None:
        super().__init__()
        self.ticket_code = ticket_code

    async def on_submit(self, interaction: discord.Interaction) -> None:
        ticket = update_ticket_status(
            self.ticket_code, "RESOLVED", resolution_notes=self.resolution.value
        )
        if ticket:
            await interaction.response.send_message(
                f"Ticket **{self.ticket_code}** marked as **RESOLVED**.\n"
                f"Notes: {self.resolution.value}",
                ephemeral=True,
            )
            await _notify_ambassador(interaction.client, ticket, "resolved", self.resolution.value)
        else:
            await interaction.response.send_message("Ticket not found.", ephemeral=True)


class ReplyModal(ui.Modal, title="Reply to Ambassador"):
    reply_text = ui.TextInput(
        label="Your Reply",
        style=discord.TextStyle.paragraph,
        placeholder="Type your response to the ambassador...",
        required=True,
        max_length=1500,
    )

    def __init__(self, ticket_code: str) -> None:
        super().__init__()
        self.ticket_code = ticket_code

    async def on_submit(self, interaction: discord.Interaction) -> None:
        ticket = get_ticket(self.ticket_code)
        if not ticket:
            await interaction.response.send_message("Ticket not found.", ephemeral=True)
            return

        await interaction.response.send_message(
            f"Reply sent for **{self.ticket_code}**.",
            ephemeral=True,
        )

        await _relay_reply_to_ambassador(
            interaction.client, ticket, interaction.user, self.reply_text.value
        )


class TicketActionView(ui.View):
    def __init__(self, ticket_code: str) -> None:
        super().__init__(timeout=None)
        self.ticket_code = ticket_code

    @ui.button(label="Acknowledge", style=discord.ButtonStyle.success, custom_id="ticket_ack")
    async def acknowledge(self, interaction: discord.Interaction, button: ui.Button) -> None:
        ticket = update_ticket_status(self.ticket_code, "ACKNOWLEDGED")
        if ticket:
            button.disabled = True
            button.label = "Acknowledged"
            await interaction.response.edit_message(view=self)
            await _notify_ambassador(interaction.client, ticket, "acknowledged")
        else:
            await interaction.response.send_message("Ticket not found.", ephemeral=True)

    @ui.button(label="Reply", style=discord.ButtonStyle.primary, custom_id="ticket_reply")
    async def reply(self, interaction: discord.Interaction, button: ui.Button) -> None:
        await interaction.response.send_modal(ReplyModal(self.ticket_code))

    @ui.button(label="Resolve", style=discord.ButtonStyle.danger, custom_id="ticket_resolve")
    async def resolve(self, interaction: discord.Interaction, button: ui.Button) -> None:
        await interaction.response.send_modal(ResolveModal(self.ticket_code))


class PersistentTicketView(ui.View):
    def __init__(self) -> None:
        super().__init__(timeout=None)

    @ui.button(label="Acknowledge", style=discord.ButtonStyle.success, custom_id="ticket_ack")
    async def acknowledge(self, interaction: discord.Interaction, button: ui.Button) -> None:
        ticket_code = _extract_ticket_code(interaction)
        if not ticket_code:
            await interaction.response.send_message("Could not find ticket.", ephemeral=True)
            return
        ticket = update_ticket_status(ticket_code, "ACKNOWLEDGED")
        if ticket:
            button.disabled = True
            button.label = "Acknowledged"
            await interaction.response.edit_message(view=self)
            await _notify_ambassador(interaction.client, ticket, "acknowledged")

    @ui.button(label="Reply", style=discord.ButtonStyle.primary, custom_id="ticket_reply")
    async def reply(self, interaction: discord.Interaction, button: ui.Button) -> None:
        ticket_code = _extract_ticket_code(interaction)
        if ticket_code:
            await interaction.response.send_modal(ReplyModal(ticket_code))
        else:
            await interaction.response.send_message("Could not find ticket.", ephemeral=True)

    @ui.button(label="Resolve", style=discord.ButtonStyle.danger, custom_id="ticket_resolve")
    async def resolve(self, interaction: discord.Interaction, button: ui.Button) -> None:
        ticket_code = _extract_ticket_code(interaction)
        if ticket_code:
            await interaction.response.send_modal(ResolveModal(ticket_code))
        else:
            await interaction.response.send_message("Could not find ticket.", ephemeral=True)


def _extract_ticket_code(interaction: discord.Interaction) -> str | None:
    if interaction.message and interaction.message.embeds:
        title = interaction.message.embeds[0].title or ""
        for part in title.split():
            if part.startswith("HRCC-"):
                return part.rstrip(" —")
    return None


async def _notify_ambassador(
    client: discord.Client,
    ticket: dict,
    action: str,
    notes: str = "",
) -> None:
    try:
        channel = client.get_channel(ticket["channel_id"])
        if channel is None:
            channel = await client.fetch_channel(ticket["channel_id"])

        poc_display = ticket["poc_name"].title()
        if action == "acknowledged":
            msg = f"**{poc_display}** has acknowledged your ticket **{ticket['ticket_code']}** and is investigating."
        elif action == "resolved":
            msg = f"**{poc_display}** has resolved your ticket **{ticket['ticket_code']}**."
            if notes:
                msg += f"\n> {notes}"
        else:
            return

        await channel.send(msg)  # type: ignore[union-attr]
    except Exception:
        log.exception("Failed to notify ambassador for ticket %s", ticket["ticket_code"])


async def _relay_reply_to_ambassador(
    client: discord.Client,
    ticket: dict,
    poc_user: discord.User,
    reply_text: str,
) -> None:
    try:
        channel = client.get_channel(ticket["channel_id"])
        if channel is None:
            channel = await client.fetch_channel(ticket["channel_id"])

        msg = (
            f"**Reply from {poc_user.display_name}** regarding ticket **{ticket['ticket_code']}**:\n"
            f"> {reply_text}"
        )
        await channel.send(msg)  # type: ignore[union-attr]
    except Exception:
        log.exception("Failed to relay reply for ticket %s", ticket["ticket_code"])
