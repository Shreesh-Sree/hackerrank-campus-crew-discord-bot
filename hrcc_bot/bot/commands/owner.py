"""Owner-only commands."""
from __future__ import annotations

import discord
from discord import app_commands
from hrcc_bot.bot.auth_gate import Role, get_user_role


def register(tree: app_commands.CommandTree) -> None:
    @tree.command(name="owner_api_status", description="[Owner] Check HRW API health and quota")
    async def owner_api_status_cmd(interaction: discord.Interaction) -> None:
        role = get_user_role(interaction.user.id)
        if role < Role.OWNER:
            await interaction.response.send_message("Owner access required.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)
        from hrcc_bot.services.hrw_api import get_tests, get_hrw_users, get_questions
        try:
            tests = await get_tests(limit=1)
            users = await get_hrw_users(limit=1)
            questions = await get_questions(limit=1)

            embed = discord.Embed(title="HRW API Status", color=discord.Color.green())
            embed.add_field(name="Tests", value=str(tests.get("total", "?")), inline=True)
            embed.add_field(name="Users", value=str(users.get("total", "?")), inline=True)
            embed.add_field(name="Questions", value=str(questions.get("total", "?")), inline=True)
            embed.add_field(name="Status", value="Connected", inline=True)
            await interaction.followup.send(embed=embed, ephemeral=True)
        except Exception as exc:
            await interaction.followup.send(f"HRW API Error: {exc}", ephemeral=True)
