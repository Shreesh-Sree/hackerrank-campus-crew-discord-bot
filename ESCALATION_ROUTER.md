# Automated Escalation Router & Direct Message (DM) Dispatch System (`ESCALATION_ROUTER.md`)

> **Technical Specification for Autonomous Issue Triage & POC Direct Notification**  
> Document Version: 1.0  
> Target System: HackerRank Campus Crew Super Agent (`hrcc_bot`)

---

## 1. Executive Summary & Objective

In campus communities, student ambassadors frequently experience time-sensitive issues (e.g., live contest portal outages, pending HRW recruiter invitations 2 hours before a competition, or winner reward activation spreadsheets).

Previously, ambassadors had to manually locate lead usernames, draft messages, and wait indefinitely. The **Automated Escalation Router** transforms `hrcc_bot` into an autonomous dispatch hub:
1. It analyzes the urgency, context, and domain of the user's issue.
2. It drafts a structured, standardized **Escalation Ticket Card**.
3. It directly transmits the ticket to the Discord Direct Messages (DMs) of the designated Point of Contact (**Sanskruti**, **Sreesanth**, or **Nitish**).
4. It provides interactive Discord buttons (`[Acknowledge]`, `[Mark Resolved]`, `[Reply to Ambassador]`) allowing the POC to manage the issue directly from their mobile/desktop Discord DM without switching channels.

---

## 2. Escalation Matrix & Routing Logic

```
                          [ Inbound Message / Command ]
                                       │
                                       ▼
                       [ Severity & Domain Classifier ]
                                       │
            ┌──────────────────────────┼──────────────────────────┐
            ▼                          ▼                          ▼
    [ Operations / Rewards ]   [ Technical / Platform ]    [ Design / Brand ]
            │                          │                          │
            ▼                          ▼                          ▼
       Sanskruti                   Sreesanth                    Nitish
    (Program Manager)          (Technical Lead)             (Design Lead)
            │                          │                          │
            └──────────────────────────┼──────────────────────────┘
                                       │
                                       ▼
                         [ Anti-Spam / Rate-Limit Gate ]
                                       │
                                       ▼
                          [ Direct Message Dispatch ]
                                       │
                    ┌──────────────────┴──────────────────┐
                    ▼                                     ▼
          [ POC Receives DM Embed ]            [ Ambassador Receives Notice ]
          • Ticket ID & Student Info           • "Ticket #104 dispatched to
          • Issue description & logs             Sreesanth. You will be
          • Action Buttons                       notified upon review."
```

### Routing Directory & Ownership Rules

| Lead | Discord Role / ID Key | Trigger Keywords & Scenarios | Priority SLA |
| :--- | :--- | :--- | :---: |
| **Sanskruti** | `POC_DISCORD_SANSKRUTI` | • Winner spreadsheets / CSV submissions<br>• Merchandise tracking & delivery delays<br>• Speaker, mentor, or judge requests<br>• Onboarding & welcome kit inquiries<br>• College permission letter requests | **P1** (12–24h) |
| **Sreesanth** | `POC_DISCORD_SREESANTH` | • Live contest 404 / 500 errors<br>• HRW account pending before event<br>• Candidate compiler / evaluation bugs<br>• SkillUp platform integration errors<br>• Account lockouts | **P0 (Emergency)** (< 2h)<br>**P1 (Standard)** (12h) |
| **Nitish** | `POC_DISCORD_NITISH` | • Canva certificate vector asset requests<br>• Official logo package requests<br>• Poster & social media creative review<br>• Brand guideline compliance checks | **P2** (24–48h) |

---

## 3. Severity Classification Engine

Before routing any message to a POC's private DMs, the classifier assigns a deterministic **Priority Level**:

```python
class EscalationPriority(Enum):
    P0_EMERGENCY = "P0_EMERGENCY"   # Immediate contest blocker (live event outage)
    P1_OPERATIONAL = "P1_OPERATIONAL" # Blocked workflow (rewards, pending invites)
    P2_GENERAL = "P2_GENERAL"       # Visual assets, questions, feedback
```

### Classification Heuristics
- **P0 (Emergency):**
  - Triggered if message contains phrases like: *"contest is live right now"*, *"students getting 500 error"*, *"test link broken"*, *"event starts in 30 minutes"*.
  - Behavior: Instant DM dispatch with an emergency alert ping (`🚨 P0 URGENT: Live Event Issue`).
- **P1 (Operational):**
  - Triggered if message contains: *"winner spreadsheet attached"*, *"HRW activation missing"*, *"speaker confirmation needed"*.
  - Behavior: Standard DM dispatch with organized context.
- **P2 (General):**
  - Assets, Canva templates, logo downloads.
  - Behavior: The bot attempts to answer directly first; routes to Nitish only if custom assistance is requested.

---

## 4. Anti-Harassment & Anti-Spam Guardrails

To protect HackerRank leads from DM flooding, the router enforces **strict protection policies**:

1. **Explicit Confirmation Modal:**  
   In public channels, the bot never routes a casual question to a POC's DM without student confirmation. It asks:
   > *"Would you like me to dispatch an official ticket to Sreesanth regarding this technical issue?"*  
   > *(User clicks `[Confirm Dispatch]` button)*.
2. **Per-Ambassador Cooldowns:**  
   Each user is capped at **1 escalation ticket every 2 hours** (unless marked P0 Emergency).
3. **Automated De-duplication:**  
   If an ambassador submits the same issue twice, the bot links the new message to the existing ticket instead of pinging the lead again.
4. **Out-of-Scope Blocking:**  
   Casual questions answered in the handbook (e.g., *"What are the reward tiers?"*) are **automatically resolved** by the Vector-less RAG and rejected from DM routing.

---

## 5. The POC Direct Message Interface (Interactive Embed)

When a ticket is dispatched, the lead receives a clean Discord Embed with interactive components:

```
┌─────────────────────────────────────────────────────────────┐
│ 🎫 CAMPUS CREW TICKET #1042 — P0 EMERGENCY                  │
├─────────────────────────────────────────────────────────────┤
│ 👤 Ambassador: Siddharth Verma (@siddharth_v)               │
│ 🏫 College:    National Institute of Technology, Trichy     │
│ 📅 Timestamp:  2026-09-19 16:45 IST                         │
│ 📍 Channel:    #support-live (Guild: HackerRank Campus Crew)│
│                                                             │
│ 📝 Issue Summary:                                           │
│ "Our contest 'CodeWars 2026' is starting in 45 minutes and  │
│ my HRW invite is still not activated. Test link is inaccessible│
│ to students."                                               │
│                                                             │
│ 📎 Attachments: error_screenshot.png [Preview]             │
├─────────────────────────────────────────────────────────────┤
│ [ ✅ Acknowledge ]   [ 💬 Reply to Student ]   [ 🔒 Resolve ]│
└─────────────────────────────────────────────────────────────┘
```

### Interactive Button Handlers:
1. **`[ ✅ Acknowledge ]`:**
   - Immediately updates the ticket status to `ACKNOWLEDGED`.
   - Sends an automated reply back to the student in the original channel:
     > *"✅ **Sreesanth** has acknowledged your ticket (#1042) and is investigating."*
2. **`[ 💬 Reply to Student ]`:**
   - Opens a native Discord modal on the lead's screen.
   - The lead types a message (e.g. *"Account activated, please refresh HRW dashboard now"*).
   - The bot relays this response directly to the student in the channel, citing the ticket ID.
3. **`[ 🔒 Resolve ]`:**
   - Closes the ticket and archives the audit log.

---

## 6. Bi-Directional Relay Architecture

```
[ Ambassador in Channel ]                    [ hrcc_bot Engine ]                      [ Lead in Private DM ]
            │                                         │                                         │
            ├── 1. Submits Ticket (#1042) ───────────►│                                         │
            │                                         ├── 2. Dispatches Formatted Embed ───────►│
            │                                         │                                         │
            │   3. "Ticket dispatched..." ◄───────────┤                                         │
            │                                         │                                         │
            │                                         │◄── 4. Clicks [Acknowledge] ─────────────┤
            │   5. "Lead has acknowledged" ◄──────────┤                                         │
            │                                         │                                         │
            │                                         │◄── 6. Submits Reply Modal ──────────────┤
            │   7. Relays lead's answer ◄─────────────┤                                         │
```

---

## 7. Configuration Specification

The router reads designated Discord user IDs from `.env`:

```bash
# Point of Contact (POC) Discord User IDs for DM Routing
POC_DISCORD_SANSKRUTI="389472918237482910"
POC_DISCORD_SREESANTH="1207248110879768620"
POC_DISCORD_NITISH="492019482910492819"

# Router Configuration
ESCALATION_COOLDOWN_HOURS=2
ENABLE_DM_ROUTING=true
ENABLE_P0_OVERRIDE=true
```
