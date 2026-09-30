"""Moderator commands."""
from __future__ import annotations

import discord
from discord import app_commands
from hrcc_bot.bot.auth_gate import Role, get_user_role
from hrcc_bot.core.db import (
    TIER_BADGES,
    get_all_tickets,
    get_ambassador_events,
    get_ambassador_points,
    get_ambassador_profile,
    get_hrw_link,
    get_ticket_stats,
)


def register(tree: app_commands.CommandTree) -> None:
    @tree.command(name="mod_lookup", description="[Mod] View any ambassador's profile and events")
    @app_commands.describe(user="Ambassador to look up")
    async def mod_lookup_cmd(interaction: discord.Interaction, user: discord.User) -> None:
        role = get_user_role(interaction.user.id)
        if role < Role.MODERATOR:
            await interaction.response.send_message("Moderator access required.", ephemeral=True)
            return

        profile = get_ambassador_profile(user.id)
        events = get_ambassador_events(user.id)
        pts = get_ambassador_points(user.id)
        link = get_hrw_link(user.id)

        embed = discord.Embed(title=f"[Mod] Ambassador — {user.display_name}", color=discord.Color.dark_teal())
        if link:
            embed.add_field(name="HRW", value=f"{link['hrw_name']} ({link['hrw_email']})", inline=False)
        if profile:
            embed.add_field(name="College", value=profile.get("college_name") or "—", inline=True)
            embed.add_field(name="Country", value=f"{profile.get('country', '—')} ({profile.get('region', '—')})", inline=True)
            embed.add_field(name="Stage", value=profile.get("current_stage", "—"), inline=True)
        if pts:
            badge = TIER_BADGES.get(pts["tier_name"], "")
            embed.add_field(name="Points", value=f"{badge} {pts['total_points']} ({pts['tier_name']})", inline=True)
            embed.add_field(name="Contests", value=str(pts["contests_hosted"]), inline=True)
        if events:
            lines = [f"- {e['event_name']} ({e.get('event_date','—')}) — {e['participant_count']}p" for e in events[:5]]
            embed.add_field(name=f"Events ({len(events)})", value="\n".join(lines), inline=False)

        await interaction.response.send_message(embed=embed, ephemeral=True)

    @tree.command(name="mod_tickets", description="[Mod] View all open escalation tickets")
    async def mod_tickets_cmd(interaction: discord.Interaction) -> None:
        role = get_user_role(interaction.user.id)
        if role < Role.MODERATOR:
            await interaction.response.send_message("Moderator access required.", ephemeral=True)
            return

        tickets = get_all_tickets(limit=15)
        open_tickets = [t for t in tickets if t["status"] != "RESOLVED"]

        if not open_tickets:
            await interaction.response.send_message("No open tickets.", ephemeral=True)
            return

        embed = discord.Embed(title="Open Escalation Tickets", color=discord.Color.orange())
        for t in open_tickets[:10]:
            embed.add_field(
                name=f"{t['ticket_code']} — {t['urgency']} ({t['status']})",
                value=f"**By:** {t['author_name']} | **To:** {t['poc_name'].title()}\n{t['description'][:100]}",
                inline=False,
            )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @tree.command(name="mod_activity", description="[Mod] View ambassador activity summary")
    async def mod_activity_cmd(interaction: discord.Interaction) -> None:
        role = get_user_role(interaction.user.id)
        if role < Role.MODERATOR:
            await interaction.response.send_message("Moderator access required.", ephemeral=True)
            return

        from hrcc_bot.core.db import get_inactive_ambassadors_this_month
        inactive = get_inactive_ambassadors_this_month()
        stats = get_ticket_stats()

        embed = discord.Embed(title="Monthly Activity Overview", color=discord.Color.blue())
        embed.add_field(name="Inactive Ambassadors", value=str(len(inactive)), inline=True)
        embed.add_field(name="Open Tickets", value=str(stats["PENDING"]), inline=True)
        embed.add_field(name="Total Tickets", value=str(stats["total"]), inline=True)

        if inactive:
            names = [a["ambassador_name"] for a in inactive[:10]]
            embed.add_field(name="No Event This Month", value="\n".join(f"- {n}" for n in names), inline=False)

        await interaction.response.send_message(embed=embed, ephemeral=True)
