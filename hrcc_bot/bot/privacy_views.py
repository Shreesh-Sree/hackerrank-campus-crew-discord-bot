from __future__ import annotations

import json
import io
import logging

import discord
from discord import ui

from hrcc_bot.core.db import log_audit
from hrcc_bot.core.privacy import delete_user_data, export_user_data

log = logging.getLogger("hrcc.privacy_views")


def build_export_file(user_id: int) -> tuple[discord.File | None, int]:
    """JSON export of a user's data; returns (file or None if nothing stored, row count)."""
    data = export_user_data(user_id)
    rows = sum(len(v) for v in data.values())
    if not rows:
        return None, 0
    payload = json.dumps({"discord_user_id": user_id, "data": data}, indent=2, default=str)
    return discord.File(io.BytesIO(payload.encode()), filename=f"hrcc_data_{user_id}.json"), rows


def summarize_deletion(counts: dict[str, int]) -> str:
    if not counts:
        return "No stored data was found."
    return "\n".join(f"- {table}: {n}" for table, n in counts.items())


class ConfirmDeleteView(ui.View):
    """Two-step confirmation for irreversible data deletion."""

    def __init__(self, *, requester_id: int, subject_id: int, subject_label: str) -> None:
        super().__init__(timeout=120)
        self.requester_id = requester_id
        self.subject_id = subject_id
        self.subject_label = subject_label

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.requester_id:
            await interaction.response.send_message("This confirmation isn't for you.", ephemeral=True)
            return False
        return True

    def _disable_all(self) -> None:
        for child in self.children:
            if isinstance(child, ui.Button):
                child.disabled = True

    @ui.button(label="Delete permanently", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction: discord.Interaction, button: ui.Button) -> None:
        self._disable_all()
        self.stop()
        counts = delete_user_data(self.subject_id)
        log_audit(
            actor_id=interaction.user.id,
            actor_name="[deleted]" if interaction.user.id == self.subject_id else str(interaction.user),
            action="DATA_DELETED",
            target_id=self.subject_id,
            target_name="[deleted]",
            details=", ".join(f"{t}={n}" for t, n in counts.items()) or "no data",
        )
        await interaction.response.edit_message(
            content=f"Deleted stored data for {self.subject_label}:\n{summarize_deletion(counts)}", view=self
        )

    @ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: ui.Button) -> None:
        self._disable_all()
        self.stop()
        await interaction.response.edit_message(content="Nothing was deleted.", view=self)
