"""Admin / program-lead commands. Each command enforces its own role check."""
from __future__ import annotations

import io
import discord
from discord import app_commands
from hrcc_bot.bot.channels import announcement_channel_ids, support_channel_ids
from hrcc_bot.config import settings
from hrcc_bot.services.letter_service import generate_offer_letter_pdf
import os
from hrcc_bot.bot.auth_gate import Role, get_user_role
from hrcc_bot.core.db import (
    add_support_notice,
    deactivate_support_notice,
    get_active_support_notices,
    TIER_BADGES,
    add_moderator,
    award_points,
    get_all_ambassadors_export,
    get_all_tickets,
    get_ambassador_events,
    get_ambassador_points,
    get_ambassador_profile,
    log_audit,
    remove_moderator,
)
from hrcc_bot.bot.privacy_views import ConfirmDeleteView
from hrcc_bot.core.audit_log import search_audit_logs
from hrcc_bot.bot.commands._common import (
    LEAD_IDS,
    _dm_all_ambassadors,
    log,
)


def register(tree: app_commands.CommandTree) -> None:
    @tree.command(name="admin_stats", description="Monthly operations dashboard (leads only)")
    async def admin_stats_cmd(interaction: discord.Interaction) -> None:
        if not LEAD_IDS or interaction.user.id not in LEAD_IDS:
            await interaction.response.send_message(
                "This command is restricted to program leads.", ephemeral=True
            )
            return

        await interaction.response.defer()
        from hrcc_bot.services.scheduler import _get_all_month_stats
        stats = _get_all_month_stats()

        from datetime import datetime, timezone
        month_name = datetime.now(timezone.utc).strftime("%B %Y")

        embed = discord.Embed(title=f"Admin Dashboard — {month_name}", color=discord.Color.dark_gold())
        embed.add_field(
            name="Events",
            value=(
                f"**Total:** {stats['total_events']}\n"
                f"**Participants:** {stats['total_participants']}\n"
                f"**Merch Tier (300+):** {stats['merch_events']}"
            ),
            inline=True,
        )
        embed.add_field(
            name="Tickets",
            value=(
                f"**Pending:** {stats['tickets']['PENDING']}\n"
                f"**Acknowledged:** {stats['tickets']['ACKNOWLEDGED']}\n"
                f"**Resolved:** {stats['tickets']['RESOLVED']}\n"
                f"**MTTR:** {stats['avg_resolution_hours']}h"
            ),
            inline=True,
        )
        await interaction.followup.send(embed=embed)

    @tree.command(name="ambassador", description="View an ambassador's profile and event history")
    @app_commands.describe(user="The ambassador to look up")
    async def ambassador_cmd(interaction: discord.Interaction, user: discord.User) -> None:
        if get_user_role(interaction.user.id) < Role.ADMIN:
            await interaction.response.send_message("Admin access required.", ephemeral=True)
            return
        profile = get_ambassador_profile(user.id)
        events = get_ambassador_events(user.id)

        embed = discord.Embed(title=f"Ambassador — {user.display_name}", color=discord.Color.teal())

        pts = get_ambassador_points(user.id)
        if pts:
            badge = TIER_BADGES.get(pts["tier_name"], "🎖️")
            embed.add_field(name="Tier", value=f"{badge} {pts['tier_name']}", inline=True)
            embed.add_field(name="Points", value=str(pts["total_points"]), inline=True)
            embed.add_field(name="Contests", value=str(pts["contests_hosted"]), inline=True)

        if profile:
            embed.add_field(name="College", value=profile["college_name"] or "Not set", inline=True)
            embed.add_field(name="Stage", value=profile["current_stage"], inline=True)
            if profile["notes"]:
                embed.add_field(name="Notes", value=profile["notes"][:256], inline=False)
        else:
            embed.add_field(name="Profile", value="No profile registered yet.", inline=False)

        if events:
            total_p = sum(e["participant_count"] for e in events)
            event_lines = "\n".join(
                f"- **{e['event_name']}** ({e['event_date'] or '—'}) — {e['participant_count']} participants"
                for e in events[:5]
            )
            embed.add_field(name=f"Events ({len(events)} total, {total_p} participants)", value=event_lines, inline=False)
        else:
            embed.add_field(name="Events", value="No events recorded.", inline=False)

        await interaction.response.send_message(embed=embed, ephemeral=True)

    @tree.command(name="admin_points", description="[Admin] Manually award or deduct points")
    @app_commands.describe(user="Ambassador", points="Points to add (negative to deduct)", reason="Reason")
    async def admin_points_cmd(interaction: discord.Interaction, user: discord.User, points: int, reason: str) -> None:
        role = get_user_role(interaction.user.id)
        if role < Role.ADMIN:
            await interaction.response.send_message("Admin access required.", ephemeral=True)
            return

        award_points(
            ambassador_id=user.id, ambassador_name=user.display_name,
            points_delta=points, action_type="ADMIN_MANUAL",
            description=f"By {interaction.user.display_name}: {reason}",
        )
        log_audit(
            actor_id=interaction.user.id, actor_name=interaction.user.display_name,
            action="ADMIN_POINTS", target_id=user.id, target_name=user.display_name,
            details=f"{'+' if points > 0 else ''}{points} pts: {reason}",
        )
        await interaction.response.send_message(
            f"{'Awarded' if points > 0 else 'Deducted'} **{abs(points)}** points {'to' if points > 0 else 'from'} {user.display_name}. Reason: {reason}",
            ephemeral=True,
        )

    @tree.command(name="admin_set_mod", description="[Admin] Grant moderator role to an ambassador")
    @app_commands.describe(user="Ambassador to promote")
    async def admin_set_mod_cmd(interaction: discord.Interaction, user: discord.User) -> None:
        role = get_user_role(interaction.user.id)
        if role < Role.ADMIN:
            await interaction.response.send_message("Admin access required.", ephemeral=True)
            return

        add_moderator(user.id, interaction.user.id)
        log_audit(
            actor_id=interaction.user.id, actor_name=interaction.user.display_name,
            action="GRANT_MOD", target_id=user.id, target_name=user.display_name,
        )
        await interaction.response.send_message(f"**{user.display_name}** is now a Moderator.", ephemeral=True)

    @tree.command(name="admin_revoke", description="[Admin] Remove moderator role from a user")
    @app_commands.describe(user="User to demote")
    async def admin_revoke_cmd(interaction: discord.Interaction, user: discord.User) -> None:
        role = get_user_role(interaction.user.id)
        if role < Role.ADMIN:
            await interaction.response.send_message("Admin access required.", ephemeral=True)
            return

        remove_moderator(user.id)
        log_audit(
            actor_id=interaction.user.id, actor_name=interaction.user.display_name,
            action="REVOKE_MOD", target_id=user.id, target_name=user.display_name,
        )
        await interaction.response.send_message(f"Moderator role removed from **{user.display_name}**.", ephemeral=True)

    @tree.command(name="admin_tickets", description="[Admin] View all escalation tickets")
    async def admin_tickets_cmd(interaction: discord.Interaction) -> None:
        role = get_user_role(interaction.user.id)
        if role < Role.ADMIN:
            await interaction.response.send_message("Admin access required.", ephemeral=True)
            return

        tickets = get_all_tickets(limit=20)
        if not tickets:
            await interaction.response.send_message("No tickets found.", ephemeral=True)
            return

        embed = discord.Embed(title="All Escalation Tickets (Recent 20)", color=discord.Color.dark_orange())
        for t in tickets[:10]:
            status_emoji = {"PENDING": "⏳", "ACKNOWLEDGED": "✅", "RESOLVED": "🔒"}.get(t["status"], "?")
            embed.add_field(
                name=f"{status_emoji} {t['ticket_code']} — {t['urgency']}",
                value=f"{t['author_name']} → {t['poc_name'].title()} | {t['description'][:80]}",
                inline=False,
            )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @tree.command(name="admin_export", description="[Admin] Export full ambassador database as CSV")
    async def admin_export_cmd(interaction: discord.Interaction) -> None:
        role = get_user_role(interaction.user.id)
        if role < Role.ADMIN:
            await interaction.response.send_message("Admin access required.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)
        rows = get_all_ambassadors_export()

        if not rows:
            await interaction.followup.send("No ambassador data to export.", ephemeral=True)
            return

        import csv as csv_mod
        buf = io.StringIO()
        writer = csv_mod.DictWriter(buf, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

        file = discord.File(io.BytesIO(buf.getvalue().encode()), filename="ambassadors_export.csv")
        await interaction.followup.send(f"Exported {len(rows)} ambassadors.", file=file, ephemeral=True)

    @tree.command(name="admin_broadcast", description="[Admin] Send an announcement to all registered ambassadors")
    @app_commands.describe(message="The announcement message")
    async def admin_broadcast_cmd(interaction: discord.Interaction, message: str) -> None:
        role = get_user_role(interaction.user.id)
        if role < Role.ADMIN:
            await interaction.response.send_message("Admin access required.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)
        sent, total = await _dm_all_ambassadors(
            interaction.client, f"**Announcement from HackerRank Campus Crew:**\n\n{message}"
        )
        await interaction.followup.send(f"Broadcast sent to {sent}/{total} ambassadors.", ephemeral=True)

    @tree.command(
        name="support_broadcast",
        description="[Admin] Post an operational notice to support channels and teach it to the bot",
    )
    @app_commands.describe(
        message="The notice, e.g. 'HRW maintenance Sunday 02:00-04:00 IST'",
        expires_in_days="How long the bot should keep using this notice in answers (default 7)",
        dm_ambassadors="Also DM every registered ambassador",
    )
    async def support_broadcast_cmd(
        interaction: discord.Interaction,
        message: str,
        expires_in_days: app_commands.Range[int, 1, 90] = 7,
        dm_ambassadors: bool = False,
    ) -> None:
        if get_user_role(interaction.user.id) < Role.ADMIN:
            await interaction.response.send_message("Admin access required.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)
        notice = add_support_notice(
            message=message,
            author_id=interaction.user.id,
            author_name=str(interaction.user),
            expires_in_days=expires_in_days,
        )

        embed = discord.Embed(
            title="Campus Crew Operational Notice",
            description=message,
            color=discord.Color.gold(),
            timestamp=discord.utils.utcnow(),
        )
        embed.set_footer(text=f"Posted by {interaction.user.display_name}")

        channel_ids = announcement_channel_ids() | support_channel_ids()
        if not channel_ids and settings.discord_home_channel:
            channel_ids = {settings.discord_home_channel}
        posted = 0
        for channel_id in channel_ids:
            try:
                channel = interaction.client.get_channel(channel_id) or await interaction.client.fetch_channel(channel_id)
                await channel.send(embed=embed)  # type: ignore[union-attr]
                posted += 1
            except (discord.HTTPException, AttributeError):
                log.warning("Could not post support notice to channel %s", channel_id)

        dm_summary = ""
        if dm_ambassadors:
            sent, total = await _dm_all_ambassadors(
                interaction.client, f"**Campus Crew Operational Notice:**\n\n{message}"
            )
            dm_summary = f" DMed {sent}/{total} ambassadors."

        log_audit(
            actor_id=interaction.user.id, actor_name=str(interaction.user),
            action="SUPPORT_BROADCAST",
            details=f"notice #{notice['id'] if notice else '?'} ({expires_in_days}d): {message[:200]}",
        )
        await interaction.followup.send(
            f"Notice #{notice['id'] if notice else '?'} posted to {posted}/{len(channel_ids)} channel(s).{dm_summary} "
            f"The bot will use it in answers for {expires_in_days} day(s). Remove it early with `/support_notices`.",
            ephemeral=True,
        )

    @tree.command(name="support_notices", description="[Admin] List active operational notices, or remove one")
    @app_commands.describe(remove_id="ID of a notice to stop using in answers")
    async def support_notices_cmd(interaction: discord.Interaction, remove_id: int | None = None) -> None:
        if get_user_role(interaction.user.id) < Role.ADMIN:
            await interaction.response.send_message("Admin access required.", ephemeral=True)
            return

        if remove_id is not None:
            removed = deactivate_support_notice(remove_id)
            if removed:
                log_audit(
                    actor_id=interaction.user.id, actor_name=str(interaction.user),
                    action="SUPPORT_NOTICE_REMOVED", details=f"notice #{remove_id}",
                )
            await interaction.response.send_message(
                f"Notice #{remove_id} removed." if removed else f"No active notice #{remove_id}.",
                ephemeral=True,
            )
            return

        notices = get_active_support_notices()
        if not notices:
            await interaction.response.send_message("No active notices.", ephemeral=True)
            return
        lines = [
            f"**#{n['id']}** (until {n['expires_at'][:10]}, by {n['author_name']}): {n['message'][:180]}"
            for n in notices
        ]
        await interaction.response.send_message("\n".join(lines)[:1900], ephemeral=True)

    @tree.command(name="admin_delete_user", description="[Admin] Delete all stored data for a user (privacy request)")
    @app_commands.describe(user="The user whose data should be deleted")
    async def admin_delete_user_cmd(interaction: discord.Interaction, user: discord.User) -> None:
        if get_user_role(interaction.user.id) < Role.ADMIN:
            await interaction.response.send_message("Admin access required.", ephemeral=True)
            return
        view = ConfirmDeleteView(requester_id=interaction.user.id, subject_id=user.id, subject_label=str(user))
        await interaction.response.send_message(
            f"Permanently delete all stored data for **{user}** (`{user.id}`)? This cannot be undone.",
            view=view,
            ephemeral=True,
        )

    @tree.command(name="audit", description="[Admin] View the system audit log")
    @app_commands.describe(
        actor_id="Filter by ambassador ID (optional)",
        action="Filter by action type (optional)",
        category="Filter by category: OPS, TECH, DESIGN (optional)",
        limit="Number of entries to show (default 20)",
    )
    async def audit_cmd(
        interaction: discord.Interaction,
        actor_id: int | None = None,
        action: str | None = None,
        category: str | None = None,
        limit: int = 20,
    ) -> None:
        role = get_user_role(interaction.user.id)
        if role < Role.ADMIN:
            await interaction.response.send_message("Admin access required.", ephemeral=True)
            return

        logs = search_audit_logs(
            query_text="",
            actor_id=actor_id,
            action=action,
            category=category,
            limit=min(limit, 100),
        )

        if not logs:
            await interaction.response.send_message("No matching entries found.", ephemeral=True)
            return

        embed = discord.Embed(title="Audit Log", color=discord.Color.dark_grey())

        for e in logs[:25]:
            ts = e["created_at"][:16].replace("T", " ")
            actor = f"**{e['actor_name']}** (ID: {e['actor_id']})" if e.get("actor_name") else "Unknown"
            action_str = e.get("action", "N/A") or "N/A"
            urgency = e.get("urgency", "N/A") or "N/A"
            desc = e.get("description", "")[:100] or ""
            value = f"{actor} — `{action_str}` [{urgency}]\n{desc}" if desc else f"{actor} — `{action_str}` [{urgency}]"

            embed.add_field(name=f"{ts}", value=value, inline=False)

        embed.set_footer(text=f"Showing {min(len(logs), 25)} of {len(logs)} entries")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @tree.command(name="send_offer", description="Generate and email official HackerRank Campus Crew Offer Letter")
    @app_commands.describe(
        name="Student's Full Name",
        college="College / University Name",
        email="Student's Email Address",
        send_email="Actually send email via Stalwart Mail Server (default: False for preview)",
    )
    async def send_offer_cmd(
        interaction: discord.Interaction,
        name: str,
        college: str,
        email: str,
        send_email: bool = False,
    ) -> None:
        role = get_user_role(interaction.user.id)
        if role not in (Role.OWNER, Role.ADMIN, Role.MODERATOR):
            await interaction.response.send_message(
                "❌ You do not have permission to issue offer letters. (Requires Admin or Moderator)",
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True)

        pdf_path = f"/tmp/HackerRank_Campus_Crew_Offer_Letter_{name.replace(' ', '_')}.pdf"
        try:
            generate_offer_letter_pdf(
                name=name.strip(),
                college=college.strip(),
                output_pdf=pdf_path,
            )
        except Exception as e:
            await interaction.followup.send(f"❌ Failed to generate PDF offer letter: {e}", ephemeral=True)
            return

        file = discord.File(pdf_path, filename=os.path.basename(pdf_path))

        if not send_email:
            # Preview mode
            embed = discord.Embed(
                title="📄 Offer Letter Generated (Preview Mode)",
                description=(
                    f"**Recipient:** {name}\n"
                    f"**College:** {college}\n"
                    f"**Email:** {email}\n\n"
                    f"💡 *The letter PDF is attached below for your review.* "
                    f"To actually dispatch the email via Stalwart, set `send_email: True`."
                ),
                color=discord.Color.green(),
            )
            await interaction.followup.send(embed=embed, file=file, ephemeral=True)
        else:
            # Dispatch via offer-letter API server
            import urllib.request
            import json

            api_payload = {
                "name": name.strip(),
                "college": college.strip(),
                "email": email.strip(),
                "test_mode": False,
            }

            try:
                req = urllib.request.Request(
                    "http://127.0.0.1:5055/api/send-offer",
                    data=json.dumps(api_payload).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                )
                with urllib.request.urlopen(req, timeout=15) as resp:
                    resp_data = json.loads(resp.read().decode("utf-8"))

                if resp_data.get("status") in ("success", "skipped"):
                    status_text = "Delivered & Queued" if resp_data.get("status") == "success" else "Skipped (Already Sent)"
                    embed = discord.Embed(
                        title=f"✅ Offer Letter Dispatched — {status_text}",
                        description=(
                            f"**Recipient:** {name}\n"
                            f"**College:** {college}\n"
                            f"**Email:** {email}\n\n"
                            f"📧 Email sent via Stalwart Mail Server (`shreesh@hackerrankcampuscrew.xyz`) with DKIM signing."
                        ),
                        color=discord.Color.teal(),
                    )
                    await interaction.followup.send(embed=embed, file=file, ephemeral=True)
                else:
                    await interaction.followup.send(
                        f"⚠️ Error sending email: {resp_data.get('message')}",
                        ephemeral=True,
                    )
            except Exception as e:
                await interaction.followup.send(
                    f"❌ Failed to reach mail dispatch daemon (port 5055): {e}",
                    ephemeral=True,
                )
