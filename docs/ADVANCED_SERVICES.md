# Advanced Autonomous Services & Automation Suite (`ADVANCED_SERVICES.md`)

> **Comprehensive Specification for High-Impact Autonomous Modules**  
> Target System: HackerRank Campus Crew Super Agent (`hrcc_bot`)

---

## 1. Automated CSV Winner Validator & Canva Exporter

### The Problem
Following a monthly campus event, ambassadors must export raw test data from HackerRank for Work (HRW) or Community (HRC). Ambassadors regularly make mistakes:
- Submitting candidates who registered but scored `0` or didn't submit code.
- Including incorrect email addresses that don't match winners' HackerRank profiles.
- Formatting data incorrectly for Canva Bulk Certificate generation.

### The Solution: Attachment Processor Engine
When an ambassador uploads a `.csv` or `.xlsx` file into Discord (or via `/validate-contest` command):

```
[ Ambassador uploads contest_results.csv ]
                    │
                    ▼
       [ Attachment Parser & Sanity Check ]
                    │
                    ├── 1. Count Active Participants (Score > 0 or submissions > 0)
                    ├── 2. Calculate Reward Tier (< 300 vs >= 300)
                    ├── 3. Validate Email Domains & Syntax
                    └── 4. Rank Deduplication
                    │
                    ▼
        [ Dual Output Generation ]
                    │
         ┌──────────┴──────────┐
         ▼                     ▼
[ 1. Canva Bulk CSV ]   [ 2. Winner Activation Table ]
• Clean headers         • Top winners
• Auto-formatted dates  • Formatted for Sanskruti
• Attached as file      • Embed posted in channel
```

#### Canva Schema Normalization:
The engine converts varied platform exports into the exact schema required by Canva Bulk Create:
```csv
Full Name,Email Address,College Name,Event Name,Event Date,Rank,Score
Aarav Patel,aarav.p@gmail.com,IIT Madras,CodeFiesta 2026,2026-09-19,1,300
Divya Nair,divya.n@gmail.com,IIT Madras,CodeFiesta 2026,2026-09-19,2,285
```

---

## 2. Interactive Slash Commands Suite (`/`)

Slash commands execute with **zero LLM latency** (<5ms) using the in-memory Hierarchical Knowledge Tree:

| Command | Arguments | Output & Interactivity |
| :--- | :--- | :--- |
| **`/rewards`** | `[participants: int]` | Instant mathematical reward tier calculation. If $\ge 300$, adds an official merchandise badge and single-point-of-contact shipping guide. |
| **`/sop`** | `[type: contest \| hackathon \| workshop]` | Interactive Discord dropdown menu revealing pre-event, live-event, and post-event checklists. |
| **`/certs`** | *None* | Direct links to Design Lead Nitish's approved Canva certificate templates and a downloadable sample CSV. |
| **`/marketing`** | `[event_name] [date] [time] [url]` | Instant multi-platform promotional copy generator (formatted for Discord, WhatsApp, and LinkedIn). |
| **`/escalate`** | `[lead: sanskruti \| sreesanth \| nitish] [issue]` | Opens an interactive ticket modal that routes directly to the lead's Discord DMs. |
| **`/rules`** | `[platform: hrw \| hrc \| skillup]` | Complete rules card, explicitly highlighting the strict Chakra tab prohibition. |

---

## 3. Vision Agent (Error Screenshot Analyzer)

### The Problem
Ambassadors frequently encounter platform errors (e.g. *"This test is currently inactive"*, *"Link token expired"*, or *"Candidate disqualified"*). Instead of describing the error, they upload a screenshot.

### The Solution: Multi-Modal Error Triage
1. **Image Detection:** Listens for images uploaded in support channels.
2. **OCR / Multi-Modal Parsing:**
   - Extracts on-screen error banners, HTTP status codes, and portal headers.
   - Detects if the interface is HRW, HRC, or SkillUp.
3. **Automated Diagnostic & Resolution:**
   - If screenshot shows a **404 / Contest Inactive** on HRW $\rightarrow$ *"Your test has reached its end timestamp or is set to private. Contests cannot be reopened once closed. Check your dashboard to ensure the public link is enabled."*
   - If screenshot shows **Chakra tab** $\rightarrow$ Triggers immediate security alert warning the user to close that view.

---

## 4. Event Lifecycle & Temporal Reminders Daemon

The agent tracks event timelines to assist ambassadors autonomously:

```
[ Pre-Event: -24 Hours ] ──► "Checklist: Verify test link, confirm 15-min buffer, check proctoring."
[ Live Event: Hour 0 ]   ──► "Contest is LIVE. Technical escalation is on standby."
[ Post-Event: +24 Hours ]──► "Reminder: Export results CSV and submit winner emails to Sanskruti."
[ Post-Event: +48 Hours ]──► "Deadline alert: Submit post-event report to ensure monthly compliance."
```

- **Cron Implementation:** Lightweight async loop checking an SQLite `events` schedule table every 5 minutes.
- **Zero Framework Overhead:** Built directly using Python `asyncio` tasks without needing Celery or Redis.

---

## 5. Automated Marketing & Announcement Generator

Ambassadors often struggle to draft engaging promotional copy to drive signups.

### The `/marketing` Command Engine
When invoked, the bot returns ready-to-use copy formatted specifically for each social platform:

#### 1. Discord Announcement Copy (Markdown Embed)
```markdown
🚀 **GET READY FOR [Event Name]!** 🚀
Organized by **HackerRank Campus Crew** at **[College Name]**!

🏆 **Prizes & Rewards:**
• Top Winners: 1-Year HackerRank Infinity Plan + AI Tools Access + Mock Interview Credits!
• Official HackerRank Certificates for ALL active participants!
• Official Merchandise packs for top universities!

📅 **Date:** [Date] | ⏰ **Time:** [Time]
🔗 **Register Now:** <[Contest URL]>
```

#### 2. WhatsApp Broadcast Copy (Bold & Emoji Formatted)
```text
🔥 *BIG ANNOUNCEMENT: [Event Name]* 🔥
Calling all coders! Compete in the official HackerRank Campus Crew contest!

*Prizes:*
✅ HackerRank Infinity Plans & Mock Interviews
✅ 6-Month Access to 1,500+ AI Tools
✅ Official Certificates for all who submit code!

*Link to Join:* [Contest URL]
Don't miss out! 🚀
```

---

## 6. Autonomous Health Daemon, Canary Probes & Zero-Downtime Hot-Reload

To ensure 99.99% reliability on the `ai-server` PC:

### 1. 60-Second Canary Health Probe
- Every 60 seconds, an async background daemon queries:
  1. `GET http://127.0.0.1:8000/v1/models` (validates vLLM process).
  2. Sends a synthetic test completion: `{"model": "...", "messages": [{"role": "user", "content": "ping"}], "max_tokens": 2}`.
- **Benefits:**
  - Keeps the vLLM KV-cache and GPU kernels warm (0ms cold start when real students ask questions).
  - Detects GPU VRAM memory fragmentation or CUDA deadlocks early.

### 2. Zero-Downtime Knowledge Base Hot-Reload
- The Vector-less RAG Knowledge Tree is monitored via file modification timestamps (`os.path.getmtime("knowledge_data.yaml")`).
- When the handbook rules are updated or a Git pull occurs, the engine **hot-reloads the knowledge tree in RAM in <2 milliseconds** without restarting the Discord bot or dropping existing websocket connections.
