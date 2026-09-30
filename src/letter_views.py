"""
Interactive Discord Views for Approval, Editing, and Rejection of Letter Requests.
"""
from __future__ import annotations

import logging
import discord
from discord import ui
import json
import os

from src.db import get_ticket, update_ticket_status
from src.letter_service import generate_permission_letter_pdf, generate_offer_letter_pdf

log = logging.getLogger("hrcc.letter_views")

class EditLetterModal(ui.Modal, title="Edit Permission Letter Details"):
    ambassador_name = ui.TextInput(label="Ambassador Name", required=True, max_length=100)
    college_name = ui.TextInput(label="College / Institution Name", required=True, max_length=200)
    event_name = ui.TextInput(label="Event Name", required=True, max_length=200)
    event_date = ui.TextInput(label="Event Date", required=True, max_length=100)

    def __init__(self, ticket_code: str, details: dict) -> None:
        super().__init__()
        self.ticket_code = ticket_code
        self.details = details
        self.ambassador_name.default = details.get("ambassador_name", "")
        self.college_name.default = details.get("college_name", "")
        self.event_name.default = details.get("event_name", "")
        self.event_date.default = details.get("event_date", "")

    async def on_submit(self, interaction: discord.Interaction) -> None:
        # Update details
        self.details["ambassador_name"] = self.ambassador_name.value.strip()
        self.details["college_name"] = self.college_name.value.strip()
        self.details["event_name"] = self.event_name.value.strip()
        self.details["event_date"] = self.event_date.value.strip()

        pdf_path = f"/tmp/{self.ticket_code}_permission_letter.pdf"
        generate_permission_letter_pdf(
            self.details["ambassador_name"],
            self.details["college_name"],
            self.details["event_name"],
            self.details["event_date"],
            pdf_path
        )

        embed = interaction.message.embeds[0] if interaction.message and interaction.message.embeds else discord.Embed(title=f"Letter Request {self.ticket_code}")
        embed.description = (
            f"**Ambassador:** {self.details['ambassador_name']}\n"
            f"**College:** {self.details['college_name']}\n"
            f"**Event:** {self.details['event_name']}\n"
            f"**Event Date:** {self.details['event_date']}\n"
            f"*(Details edited by {interaction.user.display_name})*"
        )

        file = discord.File(pdf_path, filename=f"HackerRank_Permission_Letter_{self.ticket_code}.pdf")
        await interaction.response.send_message(
            f"Letter **{self.ticket_code}** updated with new details.",
            ephemeral=True
        )
        if interaction.message:
            await interaction.message.edit(embed=embed, attachments=[file])


class RejectLetterModal(ui.Modal, title="Reject Letter Request"):
    reason = ui.TextInput(
        label="Reason for Rejection",
        style=discord.TextStyle.paragraph,
        placeholder="Explain why this request is rejected...",
        required=True,
        max_length=500
    )

    def __init__(self, ticket_code: str, details: dict) -> None:
        super().__init__()
        self.ticket_code = ticket_code
        self.details = details

    async def on_submit(self, interaction: discord.Interaction) -> None:
        ticket = update_ticket_status(self.ticket_code, "RESOLVED", resolution_notes=f"REJECTED: {self.reason.value}")
        await interaction.response.send_message(
            f"Letter request **{self.ticket_code}** has been **REJECTED**.\nReason: {self.reason.value}",
            ephemeral=True
        )

        # Notify the ambassador in their channel or via DM
        author_id = self.details.get("author_id")
        channel_id = self.details.get("channel_id")
        try:
            channel = interaction.client.get_channel(channel_id) if channel_id else None
            if not channel and channel_id:
                channel = await interaction.client.fetch_channel(channel_id)
            if channel:
                await channel.send(
                    f"<@{author_id}> Your permission letter request **{self.ticket_code}** was rejected by **{interaction.user.display_name}**.\n"
                    f"> **Reason:** {self.reason.value}"
                )
        except Exception:
            log.exception("Could not notify ambassador of rejection")


class LetterApprovalView(ui.View):
    def __init__(self, ticket_code: str, details: dict) -> None:
        super().__init__(timeout=None)
        self.ticket_code = ticket_code
        self.details = details

    @ui.button(label="Approve & Send to Ambassador", style=discord.ButtonStyle.success, emoji="✅", custom_id="letter_approve")
    async def approve(self, interaction: discord.Interaction, button: ui.Button) -> None:
        # Generate the final official letter
        pdf_path = f"/tmp/{self.ticket_code}_permission_letter.pdf"
        if not os.path.exists(pdf_path):
            generate_permission_letter_pdf(
                self.details["ambassador_name"],
                self.details["college_name"],
                self.details["event_name"],
                self.details["event_date"],
                pdf_path
            )

        ticket = update_ticket_status(self.ticket_code, "RESOLVED", resolution_notes=f"APPROVED by {interaction.user.display_name}")
        
        button.disabled = True
        button.label = "Approved & Dispatched"
        for child in self.children:
            if isinstance(child, ui.Button):
                child.disabled = True
        if interaction.message:
            await interaction.message.edit(view=self)

        await interaction.response.send_message(
            f"Permission letter for **{self.ticket_code}** approved and dispatched to the ambassador!",
            ephemeral=True
        )

        # Dispatch the approved PDF directly to the student in their channel
        channel_id = self.details.get("channel_id")
        author_id = self.details.get("author_id")
        try:
            channel = interaction.client.get_channel(channel_id) if channel_id else None
            if not channel and channel_id:
                channel = await interaction.client.fetch_channel(channel_id)
            if channel:
                file = discord.File(pdf_path, filename=f"HackerRank_Permission_Letter_{self.details['event_name'].replace(' ', '_')}.pdf")
                await channel.send(
                    content=(
                        f"🎉 <@{author_id}> Great news! Your institutional permission letter request **{self.ticket_code}** "
                        f"has been **APPROVED** by **{interaction.user.display_name}**!\n"
                        f"Find your official letter attached below."
                    ),
                    file=file
                )
        except Exception:
            log.exception("Failed to dispatch approved letter to ambassador channel")

    @ui.button(label="Edit Details", style=discord.ButtonStyle.primary, emoji="✏️", custom_id="letter_edit")
    async def edit(self, interaction: discord.Interaction, button: ui.Button) -> None:
        await interaction.response.send_modal(EditLetterModal(self.ticket_code, self.details))

    @ui.button(label="Reject", style=discord.ButtonStyle.danger, emoji="❌", custom_id="letter_reject")
    async def reject(self, interaction: discord.Interaction, button: ui.Button) -> None:
        await interaction.response.send_modal(RejectLetterModal(self.ticket_code, self.details))
