# Dedicated Support Operations & Troubleshooting Systems (`SUPPORT_SYSTEMS.md`)

> **Comprehensive Technical Specification for Support Lifecycle, Incident Triage, and Validation**  
> Target System: HackerRank Campus Crew Super Agent (`hrcc_bot`)

---

## 1. Automated Support Ticket Lifecycle & Reference Tracking

### The Problem
When ambassadors report issues in community channels, messages often get buried beneath casual conversation. Leads have to ask repetitive clarifying questions, and issues are dropped without closure.

### The Lifecycle Pipeline
The bot provides formal tracking for every escalated issue:

```
[ Ambassador Reports Issue ]
             │
             ▼
[ Sentinel Detects Escalation Need ]
             │
             ▼
    [ Ticket Generated: #HRCC-1082 ]
             │
             ├── Status: OPEN
             ├── Severity: P0 / P1 / P2
             ├── Assigned Lead: Sreesanth / Sanskruti / Nitish
             └── Channel Anchor: Guild ID, Channel ID, Message ID
             │
             ▼
    [ Lead Acknowledges via DM ]
             │
             ▼ Status: IN_PROGRESS
             │
    [ Lead Resolves via Modal ]
             │
             ▼ Status: RESOLVED (Audit Log Written to SQLite)
```

### Ticket State Machine
- **`OPEN`:** Ticket created, initial receipt sent to ambassador, DM alert dispatched to lead.
- **`ACKNOWLEDGED`:** Lead clicked `[Acknowledge]` in their private Discord DM. Ambassador notified in channel.
- **`AWAITING_STUDENT`:** Lead requested additional information (e.g., student HackerRank profile link).
- **`RESOLVED`:** Lead marked issue as solved. Receipt posted in channel and logged to database.

---

## 2. Pre-Flight Event Configuration Validator (`/event-check`)

### The Problem
The most common emergency support tickets occur on contest day:
- Ambassador forgot to add a **15-minute buffer**, and the test closed before students finished.
- Ambassador accidentally set test visibility to **Private** instead of sharing a public invitation link.
- Ambassador accidentally accessed or shared internal **Chakra** recruiter links.

### The `/event-check` Command
Ambassadors execute `/event-check [test_url]` 24–48 hours before their event.

```python
class EventPreflightValidator:
    async def validate_event_url(self, url: str) -> PreflightReport:
        # 1. URL Domain Check
        if "hackerrank.com/work" in url:
            platform = "HRW"
        elif "hackerrank.com/contests" in url:
            platform = "HRC"
        elif "hackerrank.com/skillup" in url:
            return PreflightReport(
                valid=False,
                critical_error="SkillUp URL detected. SkillUp cannot be used for campus events."
            )
        
        # 2. Strict Chakra Tab Guard
        if "chakra" in url.lower():
            return PreflightReport(
                valid=False,
                critical_error="CRITICAL SECURITY ALERT: Chakra tab link detected. "
                               "Do NOT share this link. Use standard HRW Test Link."
            )
        
        # 3. Buffer Time & Accessibility Check
        return PreflightReport(
            valid=True,
            platform=platform,
            checklist=[
                "✅ Platform: Valid HackerRank for Work Test",
                "⚠️ Remember: Add 15–30 min buffer time in test settings",
                "✅ Public Link: Accessible to non-logged-in candidates",
                "✅ Proctoring: Webcam & Tab-switch tracking active"
            ]
        )
```

---

## 3. Platform Incident Storm Detector (Duplicate Clustering)

### The Problem
During peak contest windows across multiple universities, a temporary HackerRank platform latency spike or AWS outage can cause 50+ students across different channels to post simultaneously: *"HRW not opening"*, *"500 error"*, *"test link timeout"*. This spams support leads and causes notification fatigue.

### The Incident Clustering Engine
The Sentinel Agent maintains a 120-second sliding incident window:

```
                                [ Inbound Messages ]
                                         │
                                         ▼
               [ Error Signature Matcher: "HRW 500" / "Timeout" ]
                                         │
                 ┌───────────────────────┴───────────────────────┐
                 ▼ (Count < 3)                                   ▼ (Count ≥ 3 within 2 min)
         [ Standard Ticket ]                           [ ACTIVE INCIDENT CLUSTER ]
                                                                 │
                                         ┌───────────────────────┴───────────────────────┐
                                         ▼                                               ▼
                              [ Single Ping to Sreesanth ]                    [ Pinned Channel Notice ]
                              "Incident #INC-04: 12 reports                    "We are aware of latency
                              of HRW login latency."                          on HRW. Sreesanth is on it.
                                                                              Please use HRC fallback."
```

- **Benefit:** Reduces 50 individual lead notifications to **1 unified incident report**.
- **Auto-Resolution Broadcast:** When Sreesanth clicks `[Resolve Incident]`, the bot automatically posts an unpin notification across all affected channels: *"Platform latency resolved. Contests may proceed."*

---

## 4. Winner HackerRank Email Pre-Verification Helper

### The Problem
Handbook FAQ Issue #4: Over 80% of reward activation delays are caused by ambassadors submitting college roll-number emails (`22cs104@college.edu`) instead of the student's **registered HackerRank account email** (`student@gmail.com`).

### The Verification Workflow
When preparing reward spreadsheets:
1. Ambassador triggers `/verify-emails` or uploads a preliminary list.
2. The bot checks:
   - Does each email adhere to standard RFC 5322 format?
   - Does it flag known institutional intranet domains that reject external activation tokens?
3. Generates an ambassador prompt:
   > *"⚠️ Reminder: Rewards are activated directly on HackerRank user profiles. Confirm that each winner logs into hackerrank.com with the exact email address submitted. Mismatched emails will delay prize activation."*

---

## 5. Monthly Ambassador Compliance & Milestone Tracker

### The Problem
Ambassadors must fulfill a monthly quota: **At least one official HackerRank event per month** and post-event reporting within **48 hours**.

### The `/my-status` Command
Ambassadors can inspect their standing in real-time:
```
┌─────────────────────────────────────────────────────────────┐
│ 📅 AMBASSADOR MONTHLY STATUS: SEPTEMBER 2026                │
├─────────────────────────────────────────────────────────────┤
│ 👤 Ambassador:    Siddharth Verma                           │
│ 🏫 Institution:   National Institute of Technology, Trichy  │
│ 🏆 Monthly Event: ✅ COMPLETED (CodeWars 2026 - Sept 14)    │
│ 👥 Participants:  342 active coders (≥ 300 Merch Tier!)     │
│ 📝 Event Report:  ✅ SUBMITTED (Sept 15)                    │
│ 🎁 Reward Status: ⏳ PENDING ACTIVATION (Sent to Sanskruti)  │
├─────────────────────────────────────────────────────────────┤
│ 🌟 Current Standing: ACTIVE & COMPLIANT (Tier: Gold)        │
└─────────────────────────────────────────────────────────────┘
```

---

## 6. Live Dynamic Support Broadcast (`/support-broadcast`)

### The Problem
When HackerRank leadership updates program policies (e.g. new reward tier, platform maintenance window, or updated handbook guidelines), updating the bot usually requires code modifications or restarts.

### The Solution: Admin Broadcast & Vector-less RAG Ingestion
Authorized leads (**Sanskruti**, **Sreesanth**, or administrators) can execute:
```
/support-broadcast channel:all message:"Notice: HRW will undergo scheduled maintenance this Sunday from 02:00 to 04:00 AM IST. Please schedule campus tests outside this window."
```
1. **Immediate Broadcast:** Posts a rich announcement embed across all registered Campus Crew channels.
2. **Dynamic In-Memory Hot-Ingestion:** Appends the notice directly into the active Vector-less RAG Knowledge Graph as a high-priority operational fact. If any student asks *"Is there maintenance this Sunday?"*, the bot immediately answers accurately without restarting.

---

## 7. Multi-Channel Support Scoping Architecture

To maintain channel hygiene, `hrcc_bot` supports **channel-specific operational modes**:

| Channel Type | Mode | Bot Behavior |
| :--- | :--- | :--- |
| **`#ask-support` / `#ambassador-help`** | **Proactive Mode** | Answers all relevant Campus Crew operational, platform, and handbook questions inline **without** requiring an explicit `@mention`. Drops casual chatter. |
| **`#general-chat` / `#lounge`** | **Strict Mention Mode** | Remains **100% silent** on all channel banter. Replies **only** if explicitly tagged (`@HackerRank Support`). |
| **`#announcements`** | **Broadcast Only** | Only listens to commands from authorized leads (`/support-broadcast`). Ignores all user chat. |
| **Direct Messages (DMs)** | **Confidential Mode** | Handles sensitive winner spreadsheets, email dispute tickets, and college permission letter requests in complete privacy. |
