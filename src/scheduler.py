from __future__ import annotations

import logging
from datetime import datetime, timezone

import discord
from discord.ext import commands, tasks

from src.config import settings
from src.db import get_events_in_window, get_inactive_ambassadors_this_month, get_monthly_stats

log = logging.getLogger("hrcc.scheduler")


def _get_events_in_window(hours_from: int, hours_to: int) -> list[dict]:
    return get_events_in_window(hours_from, hours_to)


def _get_all_month_stats() -> dict:
    return get_monthly_stats()


class SchedulerCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    async def cog_load(self) -> None:
        self.event_reminder_loop.start()
        self.weekly_digest_loop.start()
        self.compliance_nudge_loop.start()

    async def cog_unload(self) -> None:
        self.event_reminder_loop.cancel()
        self.weekly_digest_loop.cancel()
        self.compliance_nudge_loop.cancel()

    @tasks.loop(minutes=30)
    async def event_reminder_loop(self) -> None:
        await self._check_reminders()

    @event_reminder_loop.before_loop
    async def _wait_ready(self) -> None:
        await self.bot.wait_until_ready()

    @tasks.loop(hours=24)
    async def weekly_digest_loop(self) -> None:
        now = datetime.now(timezone.utc)
        if now.weekday() != 6:
            return
        await self._send_weekly_digest()

    @weekly_digest_loop.before_loop
    async def _wait_ready_digest(self) -> None:
        await self.bot.wait_until_ready()

    @tasks.loop(hours=24)
    async def compliance_nudge_loop(self) -> None:
        now = datetime.now(timezone.utc)
        if now.day < 20 or now.day > 25:
            return
        await self._send_compliance_nudges()

    @compliance_nudge_loop.before_loop
    async def _wait_ready_compliance(self) -> None:
        await self.bot.wait_until_ready()

    async def _send_compliance_nudges(self) -> None:
        inactive = get_inactive_ambassadors_this_month()
        now = datetime.now(timezone.utc)
        month_name = now.strftime("%B")
        days_left = (now.replace(month=now.month % 12 + 1, day=1) - now).days if now.month < 12 else (now.replace(year=now.year + 1, month=1, day=1) - now).days

        for amb in inactive:
            await self._dm_ambassador(
                amb["ambassador_id"],
                f"**Monthly Compliance Reminder — {month_name}**\n\n"
                f"You haven't recorded an event this month yet. "
                f"You have **{days_left} days** remaining.\n\n"
                f"**Quick options:**\n"
                f"- `/create_event` or `/sop contest` to plan your event\n"
                f"- `/collab_browse` to find a partner for a joint event\n"
                f"- `/find_ambassador` to connect with ambassadors in your region\n\n"
                f"Running at least one HackerRank-platform event per month "
                f"is required to maintain active ambassador status.",
            )
        if inactive:
            log.info("Sent compliance nudges to %d inactive ambassadors", len(inactive))

    async def _check_reminders(self) -> None:
        events_72h = _get_events_in_window(-73, -72)
        for ev in events_72h:
            await self._dm_ambassador(
                ev["ambassador_id"],
                f"**Pre-Event Reminder (T-72h)** — {ev['event_name']}\n\n"
                f"Your event is in 3 days. Please:\n"
                f"- [ ] Test your HRW assessment link\n"
                f"- [ ] Verify recruiter permissions are active\n"
                f"- [ ] Check that questions are locked and published\n"
                f"- [ ] Start your promotion push if you haven't already",
            )

        events_24h = _get_events_in_window(-25, -24)
        for ev in events_24h:
            await self._dm_ambassador(
                ev["ambassador_id"],
                f"**Pre-Event Checklist (T-24h)** — {ev['event_name']}\n\n"
                f"Your event is **tomorrow**! Final checks:\n"
                f"- [ ] Add 30-minute buffer time to contest end\n"
                f"- [ ] Prepare student login instructions\n"
                f"- [ ] Note emergency escalation POC: **Sreesanth** (Technical), **Sanskruti** (Operations)\n"
                f"- [ ] Test the contest link in incognito mode\n"
                f"- [ ] Post final reminder to all promotion channels",
            )

        events_post24 = _get_events_in_window(24, 25)
        for ev in events_post24:
            await self._dm_ambassador(
                ev["ambassador_id"],
                f"**Post-Event Action Required (T+24h)** — {ev['event_name']}\n\n"
                f"Your event concluded yesterday. Please:\n"
                f"- [ ] Export contest results CSV from HRW/HRC\n"
                f"- [ ] Upload CSV for Canva certificate generation\n"
                f"- [ ] Verify winner emails match their HackerRank accounts\n"
                f"- [ ] Submit winner spreadsheet to **Sanskruti (Program Manager)**",
            )

    async def _send_weekly_digest(self) -> None:
        stats = _get_all_month_stats()

        now = datetime.now(timezone.utc)
        month_name = now.strftime("%B %Y")

        embed = discord.Embed(
            title=f"Weekly Lead Digest — {month_name}",
            color=discord.Color.gold(),
            timestamp=discord.utils.utcnow(),
        )
        embed.add_field(
            name="Events This Month",
            value=(
                f"**Total Events:** {stats['total_events']}\n"
                f"**Total Participants:** {stats['total_participants']}\n"
                f"**Merch-Eligible (300+):** {stats['merch_events']}"
            ),
            inline=True,
        )
        embed.add_field(
            name="Support Tickets",
            value=(
                f"**Open:** {stats['tickets']['PENDING']}\n"
                f"**Acknowledged:** {stats['tickets']['ACKNOWLEDGED']}\n"
                f"**Resolved:** {stats['tickets']['RESOLVED']}\n"
                f"**Avg Resolution:** {stats['avg_resolution_hours']}h"
            ),
            inline=True,
        )

        poc_ids = [
            settings.poc_discord_sanskruti,
            settings.poc_discord_sreesanth,
            settings.poc_discord_nitish,
        ]
        for poc_id in poc_ids:
            if poc_id:
                await self._dm_user(int(poc_id), embed=embed)

    async def _dm_ambassador(self, ambassador_id: int, content: str) -> None:
        try:
            user = await self.bot.fetch_user(ambassador_id)
            dm = await user.create_dm()
            await dm.send(content)
            log.info("Sent reminder to ambassador %s", ambassador_id)
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            log.warning("Could not DM ambassador %s", ambassador_id)

    async def _dm_user(self, user_id: int, *, embed: discord.Embed) -> None:
        try:
            user = await self.bot.fetch_user(user_id)
            dm = await user.create_dm()
            await dm.send(embed=embed)
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            log.warning("Could not DM user %s for weekly digest", user_id)


async def setup_scheduler(bot: commands.Bot) -> None:
    await bot.add_cog(SchedulerCog(bot))
