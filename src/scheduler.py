from __future__ import annotations

import logging
from collections import OrderedDict
from datetime import datetime, timezone

import discord
from discord.ext import commands, tasks

from src.config import settings
from src.db import get_events_in_window, get_inactive_ambassadors_this_month, get_monthly_stats

log = logging.getLogger("hrcc.scheduler")

# Deduplication ledger for the 5-minute contest reminder loop.
# Key: "ambassador_id|event_name|stage" — bounds memory growth.
_sent_reminders: OrderedDict[str, None] = OrderedDict()
_REMINDER_LEDGER_CAP = 1000


def _should_send(ambassador_id: int, event_name: str, stage: str) -> bool:
    key = f"{ambassador_id}|{event_name}|{stage}"
    if key in _sent_reminders:
        return False
    _sent_reminders[key] = None
    while len(_sent_reminders) > _REMINDER_LEDGER_CAP:
        _sent_reminders.popitem(last=False)
    return True


def _get_events_in_window(hours_from: int, hours_to: int) -> list[dict]:
    return get_events_in_window(hours_from, hours_to)


def _get_all_month_stats() -> dict:
    return get_monthly_stats()


class SchedulerCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    async def cog_load(self) -> None:
        self.event_reminder_loop.start()
        self.contest_reminder_loop.start()
        self.weekly_digest_loop.start()
        self.compliance_nudge_loop.start()

    async def cog_unload(self) -> None:
        self.event_reminder_loop.cancel()
        self.contest_reminder_loop.cancel()
        self.weekly_digest_loop.cancel()
        self.compliance_nudge_loop.cancel()

    @tasks.loop(minutes=30)
    async def event_reminder_loop(self) -> None:
        await self._check_reminders()

    @event_reminder_loop.before_loop
    async def _wait_ready(self) -> None:
        await self.bot.wait_until_ready()

    # ── Automated contest lifecycle reminders (5-minute cadence) ─────────

    @tasks.loop(minutes=5)
    async def contest_reminder_loop(self) -> None:
        try:
            await self._check_contest_reminders()
        except Exception:
            log.exception("Contest reminder loop iteration failed")

    @contest_reminder_loop.before_loop
    async def _wait_ready_contest(self) -> None:
        await self.bot.wait_until_ready()

    async def _check_contest_reminders(self) -> None:
        # T-24h — pre-event checklist to the HOME SUPPORT CHANNEL + DM
        for ev in _get_events_in_window(-26, -24):
            if not _should_send(ev["ambassador_id"], ev["event_name"], "T-24h"):
                continue
            await self._post_home_channel(
                f"📋 **Pre-Event Checklist (T-24h)** — {ev['event_name']}\n\n"
                f"An ambassador's contest starts in 24 hours. Final checks:\n"
                f"- [ ] HRW assessment link tested in incognito mode\n"
                f"- [ ] Contest published with correct start/end window (+30 min buffer)\n"
                f"- [ ] Student login instructions prepared (HRW first, HRC fallback if access pending)\n"
                f"- [ ] Proctoring plan confirmed — **Chakra tab is INTERNAL only, ambassadors must never open it**\n"
                f"- [ ] Standby contacts ready: **Sanskruti** (Program Manager), **Sreesanth** (Technical Lead)"
            )
            await self._dm_ambassador(
                ev["ambassador_id"],
                f"**Pre-Event Checklist (T-24h)** — {ev['event_name']}\n\n"
                f"Your contest is in 24 hours. Please confirm:\n"
                f"- [ ] HRW link tested in incognito mode\n"
                f"- [ ] Contest published with +30 minute buffer on end time\n"
                f"- [ ] Student login instructions ready (HRW; HRC as fallback if access is pending)\n"
                f"- [ ] Proctoring plan set — never open the internal **Chakra** tab\n"
                f"- [ ] Standby contacts: **Sanskruti** (Program Manager), **Sreesanth** (Technical Lead)",
            )

        # T-1h — live proctoring reminder + standby contacts
        for ev in _get_events_in_window(-2, -1):
            if not _should_send(ev["ambassador_id"], ev["event_name"], "T-1h"):
                continue
            await self._dm_ambassador(
                ev["ambassador_id"],
                f"🔴 **LIVE IN 1 HOUR — {ev['event_name']}**\n\n"
                f"**Proctoring protocol:**\n"
                f"- Stay in the venue/channel until the contest window closes (+30 min buffer)\n"
                f"- If HRW throws errors, route candidates to **HRC** (`hackerrank.com`) — never SkillUp\n"
                f"- Screenshots of any error → upload here for instant triage\n\n"
                f"**Standby contacts (escalate immediately if stuck):**\n"
                f"- **Sanskruti** — Program Manager (rewards, onboarding, judges)\n"
                f"- **Sreesanth** — Technical Lead (HRW access, platform bugs, proctoring disputes)"
            )

        # T+24h — export raw CSV and validate
        for ev in _get_events_in_window(24, 25):
            if not _should_send(ev["ambassador_id"], ev["event_name"], "T+24h"):
                continue
            await self._dm_ambassador(
                ev["ambassador_id"],
                f"📤 **Post-Event (T+24h)** — {ev['event_name']}\n\n"
                f"Your contest concluded yesterday. Please:\n"
                f"- [ ] Export the **raw contest CSV** from HRW/HRC (all columns, unedited)\n"
                f"- [ ] Run `/validate_contest` with the CSV for certificate + rewards validation\n"
                f"- [ ] Verify winner emails match their HackerRank accounts before submitting to **Sanskruti**"
            )

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

        # T-24h and T+24h are handled by contest_reminder_loop (5-minute cadence).

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

    def _localize_note(self, ambassador_id: int) -> str:
        from src.db import get_ambassador_profile
        profile = get_ambassador_profile(ambassador_id)
        if profile and profile.get("timezone_str") and profile["timezone_str"] != "UTC":
            return f"\n*Your timezone: {profile['timezone_str']}*"
        return ""

    async def _post_home_channel(self, content: str) -> None:
        """Post an announcement to the configured HOME SUPPORT CHANNEL."""
        if not settings.discord_home_channel:
            log.debug("Home support channel not configured; skipping announcement")
            return
        try:
            channel = self.bot.get_channel(settings.discord_home_channel)
            if channel is None or not isinstance(channel, discord.TextChannel):
                channel = await self.bot.fetch_channel(settings.discord_home_channel)
            if channel is None or not isinstance(channel, discord.TextChannel):
                log.warning("Home support channel %s not found", settings.discord_home_channel)
                return
            await channel.send(content)
            log.info("Posted contest announcement to home channel %s", settings.discord_home_channel)
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            log.warning("Could not post to home channel %s", settings.discord_home_channel)

    async def _dm_ambassador(self, ambassador_id: int, content: str) -> None:
        content += self._localize_note(ambassador_id)
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
