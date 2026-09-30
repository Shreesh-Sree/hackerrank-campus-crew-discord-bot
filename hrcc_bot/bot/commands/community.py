"""International & community commands: leaderboards, collaboration, showcases, analytics."""
from __future__ import annotations

import discord
from discord import app_commands, ui
from datetime import datetime, timezone
from hrcc_bot.core.db import (
    TIER_BADGES,
    create_collab_request,
    find_ambassadors_by_country,
    find_ambassadors_by_region,
    get_ambassador_profile,
    get_country_leaderboard,
    get_global_leaderboard,
    get_monthly_stats,
    get_open_collab_requests,
    get_recent_showcases,
    get_upcoming_events_calendar,
    create_showcase,
    get_region_leaderboard,
)


def register(tree: app_commands.CommandTree) -> None:
    @tree.command(name="leaderboard", description="Global, regional, or country ambassador leaderboard")
    @app_commands.describe(scope="Leaderboard scope")
    @app_commands.choices(scope=[
        app_commands.Choice(name="Global (Top 10)", value="global"),
        app_commands.Choice(name="My Region", value="my_region"),
        app_commands.Choice(name="My Country", value="my_country"),
    ])
    async def leaderboard_cmd(interaction: discord.Interaction, scope: app_commands.Choice[str]) -> None:
        profile = get_ambassador_profile(interaction.user.id)

        if scope.value == "my_country":
            country = profile["country"] if profile and profile.get("country") else ""
            if not country:
                await interaction.response.send_message("Set your country first with `/set_profile`.", ephemeral=True)
                return
            rows = get_country_leaderboard(country, limit=10)
            title = f"Country Leaderboard — {country}"
        elif scope.value == "my_region":
            region = profile["region"] if profile and profile.get("region") else ""
            if not region:
                await interaction.response.send_message("Set your country first with `/set_profile`.", ephemeral=True)
                return
            rows = get_region_leaderboard(region, limit=10)
            title = f"Region Leaderboard — {region}"
        else:
            rows = get_global_leaderboard(limit=10)
            title = "Global Ambassador Leaderboard"

        if not rows:
            await interaction.response.send_message("No ambassadors on the leaderboard yet.", ephemeral=True)
            return

        embed = discord.Embed(title=title, color=discord.Color.gold())

        lines: list[str] = []
        for i, r in enumerate(rows, start=1):
            badge = TIER_BADGES.get(r["tier_name"], "🎖️")
            medal = {1: "🥇", 2: "🥈", 3: "🥉"}.get(i, f"`#{i}`")
            country_flag = r.get("country", "")
            loc = f" ({country_flag})" if country_flag else ""
            lines.append(
                f"{medal} **{r['ambassador_name']}**{loc} — {r['total_points']} pts "
                f"{badge} | {r['contests_hosted']} contests"
            )

        embed.description = "\n".join(lines)
        embed.set_footer(text="Points: +100/contest, +150/300+ participants | /set_profile to set your country")
        await interaction.response.send_message(embed=embed)

    @tree.command(name="find_ambassador", description="Find ambassadors in a country or region")
    @app_commands.describe(
        scope="Search by country or region",
        query="Country name (e.g. Brazil) or region (e.g. Asia-Pacific)",
    )
    @app_commands.choices(scope=[
        app_commands.Choice(name="Country", value="country"),
        app_commands.Choice(name="Region", value="region"),
    ])
    async def find_ambassador_cmd(
        interaction: discord.Interaction,
        scope: app_commands.Choice[str],
        query: str,
    ) -> None:
        if scope.value == "region":
            rows = find_ambassadors_by_region(query.strip(), limit=20)
            title = f"Ambassadors in {query.strip()}"
        else:
            rows = find_ambassadors_by_country(query.strip(), limit=20)
            title = f"Ambassadors in {query.strip()}"

        if not rows:
            await interaction.response.send_message(
                f"No ambassadors found in {query.strip()}.", ephemeral=True
            )
            return

        embed = discord.Embed(title=title, color=discord.Color.teal())
        lines = []
        for r in rows[:15]:
            college = r.get("college_name", "")
            country = r.get("country", "")
            stage = r.get("current_stage", "")
            lines.append(f"- **{r['ambassador_name']}** — {college}, {country} ({stage})")
        embed.description = "\n".join(lines)
        if len(rows) > 15:
            embed.set_footer(text=f"Showing 15 of {len(rows)} ambassadors")
        await interaction.response.send_message(embed=embed)

    class CollabModal(ui.Modal, title="Cross-Campus Collaboration Request"):
        event_name_input = ui.TextInput(label="Event Name", required=True, max_length=200)
        event_format_input = ui.TextInput(
            label="Format (contest / hackathon / workshop / joint)",
            required=True, max_length=50,
        )
        proposed_date_input = ui.TextInput(label="Proposed Date (e.g. 15 November 2026)", required=True, max_length=50)
        target_country_input = ui.TextInput(
            label="Target Country or Region (or 'any')",
            required=False, max_length=100, placeholder="any",
        )
        message_input = ui.TextInput(
            label="Message to potential collaborators",
            style=discord.TextStyle.paragraph,
            required=False, max_length=500,
        )

        async def on_submit(self, interaction: discord.Interaction) -> None:
            req = create_collab_request(
                requester_id=interaction.user.id,
                requester_name=interaction.user.display_name,
                target_country=self.target_country_input.value.strip() or "any",
                event_name=self.event_name_input.value.strip(),
                event_format=self.event_format_input.value.strip(),
                proposed_date=self.proposed_date_input.value.strip(),
                message=self.message_input.value.strip(),
            )
            await interaction.response.send_message(
                f"Collaboration request **#{req.get('id', '?')}** posted!\n"
                f"**Event:** {self.event_name_input.value}\n"
                f"**Target:** {self.target_country_input.value or 'Open to all'}\n"
                f"Other ambassadors can find this via `/collab_browse`.",
                ephemeral=True,
            )

    @tree.command(name="collab_request", description="Post a cross-campus collaboration request")
    async def collab_request_cmd(interaction: discord.Interaction) -> None:
        await interaction.response.send_modal(CollabModal())

    @tree.command(name="collab_browse", description="Browse open collaboration requests from ambassadors worldwide")
    async def collab_browse_cmd(interaction: discord.Interaction) -> None:
        requests = get_open_collab_requests(limit=10)
        if not requests:
            await interaction.response.send_message("No open collaboration requests right now.", ephemeral=True)
            return

        embed = discord.Embed(title="Open Collaboration Requests", color=discord.Color.purple())
        for req in requests:
            target = req.get("target_country", "any")
            embed.add_field(
                name=f"#{req['id']} — {req['event_name']}",
                value=(
                    f"**By:** {req['requester_name']} | **Format:** {req.get('event_format', '—')}\n"
                    f"**Date:** {req.get('proposed_date', '—')} | **Target:** {target}\n"
                    f"{req.get('message', '')[:100]}"
                ),
                inline=False,
            )
        embed.set_footer(text="DM the requester to discuss, or use /collab_request to post your own!")
        await interaction.response.send_message(embed=embed)

    class ShowcaseModal(ui.Modal, title="Share Your Event Highlight"):
        event_name_input = ui.TextInput(label="Event Name", required=True, max_length=200)
        participants_input = ui.TextInput(label="Active Participants", required=True, max_length=10)
        top_winner_input = ui.TextInput(label="Top Winner Name", required=False, max_length=100)
        highlight_input = ui.TextInput(
            label="Key Highlight / Takeaway",
            style=discord.TextStyle.paragraph,
            required=True, max_length=500,
            placeholder="What made this event special?",
        )

        async def on_submit(self, interaction: discord.Interaction) -> None:
            try:
                pcount = int(self.participants_input.value.strip())
            except ValueError:
                pcount = 0

            profile = get_ambassador_profile(interaction.user.id)
            country = profile.get("country", "") if profile else ""

            create_showcase(
                ambassador_id=interaction.user.id,
                ambassador_name=interaction.user.display_name,
                event_name=self.event_name_input.value.strip(),
                country=country,
                participant_count=pcount,
                highlight=self.highlight_input.value.strip(),
                top_winner=self.top_winner_input.value.strip(),
            )

            embed = discord.Embed(
                title=f"Event Showcase — {self.event_name_input.value}",
                color=discord.Color.gold(),
            )
            embed.add_field(name="Ambassador", value=interaction.user.display_name, inline=True)
            embed.add_field(name="Country", value=country or "—", inline=True)
            embed.add_field(name="Participants", value=str(pcount), inline=True)
            if self.top_winner_input.value:
                embed.add_field(name="Top Winner", value=self.top_winner_input.value, inline=True)
            embed.add_field(name="Highlight", value=self.highlight_input.value[:500], inline=False)

            await interaction.response.send_message(embed=embed)

    @tree.command(name="showcase", description="Share your event highlight with the community")
    async def showcase_cmd(interaction: discord.Interaction) -> None:
        await interaction.response.send_modal(ShowcaseModal())

    @tree.command(name="showcase_feed", description="Browse recent event highlights from ambassadors worldwide")
    async def showcase_feed_cmd(interaction: discord.Interaction) -> None:
        showcases = get_recent_showcases(limit=10)
        if not showcases:
            await interaction.response.send_message("No showcases yet. Be the first — use `/showcase`!")
            return

        embed = discord.Embed(title="Event Showcase Feed", color=discord.Color.gold())
        for s in showcases:
            country = f" ({s.get('country', '')})" if s.get("country") else ""
            embed.add_field(
                name=f"{s['event_name']}{country}",
                value=(
                    f"**By:** {s['ambassador_name']} | **Participants:** {s['participant_count']}\n"
                    f"{s.get('highlight', '')[:120]}"
                ),
                inline=False,
            )
        await interaction.response.send_message(embed=embed)

    @tree.command(name="calendar", description="View upcoming events from ambassadors worldwide")
    async def calendar_cmd(interaction: discord.Interaction) -> None:
        events = get_upcoming_events_calendar()
        if not events:
            await interaction.response.send_message("No upcoming events scheduled.")
            return

        embed = discord.Embed(title="Upcoming Events Calendar", color=discord.Color.teal())
        for e in events:
            embed.add_field(
                name=f"{e.get('event_date', '?')[:10]} — {e['event_name'][:40]}",
                value=f"By: {e['ambassador_name']} | Platform: {e.get('platform', '?')}",
                inline=False,
            )
        embed.set_footer(text="Submit events via /create_event or /submit_report to appear here.")
        await interaction.response.send_message(embed=embed)

    @tree.command(name="trends", description="Global program analytics and growth trends")
    async def trends_cmd(interaction: discord.Interaction) -> None:
        stats = get_monthly_stats()
        lb = get_global_leaderboard(limit=1000)

        total_ambassadors = len(lb)
        total_points = sum(a["total_points"] for a in lb)
        total_contests = sum(a["contests_hosted"] for a in lb)
        countries = len(set(a.get("country", "") for a in lb if a.get("country")))
        regions = len(set(a.get("region", "") for a in lb if a.get("region")))

        tiers = {"Apprentice Ambassador": 0, "Campus Lead": 0, "National Fellow": 0, "Hall of Fame": 0}
        for a in lb:
            tier = a.get("tier_name", "Apprentice Ambassador")
            tiers[tier] = tiers.get(tier, 0) + 1

        month_name = datetime.now(timezone.utc).strftime("%B %Y")

        embed = discord.Embed(title=f"Program Trends — {month_name}", color=discord.Color.dark_purple())
        embed.add_field(
            name="Global Reach",
            value=(
                f"**Ambassadors:** {total_ambassadors}\n"
                f"**Countries:** {countries}\n"
                f"**Regions:** {regions}"
            ),
            inline=True,
        )
        embed.add_field(
            name="This Month",
            value=(
                f"**Events:** {stats['total_events']}\n"
                f"**Participants:** {stats['total_participants']}\n"
                f"**Merch Events:** {stats['merch_events']}"
            ),
            inline=True,
        )
        embed.add_field(
            name="All-Time",
            value=(
                f"**Total Contests:** {total_contests}\n"
                f"**Total Points:** {total_points}"
            ),
            inline=True,
        )
        embed.add_field(
            name="Tier Distribution",
            value="\n".join(
                f"{TIER_BADGES.get(t, '?')} **{t}:** {c}" for t, c in tiers.items()
            ),
            inline=False,
        )
        await interaction.response.send_message(embed=embed)
