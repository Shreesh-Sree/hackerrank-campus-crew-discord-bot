# HackerRank Campus Crew Super Agent

An autonomous, production-grade Discord agent for the **HackerRank Campus Crew** global ambassador program. Built with **LangGraph**, **LangChain**, and **discord.py**, powered by local **vLLM** inference with **HackerRank for Work API** integration.

**44 source files | 8,974 lines | 49 slash commands | 11 database tables | 283 tests | 5-tier RBAC**

The agent manages the complete ambassador lifecycle across 60+ countries — onboarding, identity verification, event planning, real-time contest monitoring, automated reward calculation, certificate generation, gamification, cross-border collaboration, and program analytics — while enforcing strict operational boundaries from the official Ambassador Handbook.

---

## Table of Contents

- [Architecture](#architecture)
- [Authentication & Access Control](#authentication--access-control)
- [Slash Commands (49)](#slash-commands-49)
- [Autonomous Agent Capabilities](#autonomous-agent-capabilities)
- [HackerRank for Work API Integration](#hackerrank-for-work-api-integration)
- [International Gamification System](#international-gamification-system)
- [Privacy & Security Model](#privacy--security-model)
- [Database Schema](#database-schema)
- [Prompt Architecture](#prompt-architecture)
- [Project Structure](#project-structure)
- [Setup & Deployment](#setup--deployment)
- [Tech Stack](#tech-stack)

---

## Architecture

```
                           [ Discord Message / Slash Command ]
                                          |
                           ┌──────────────┴──────────────┐
                           |                              |
                    [ Auth Gate ]                   [ DM Blocker ]
                    Role check:                    "I only work in
                    UNREGISTERED?                   the server."
                    → Block + suggest
                      /register
                           |
              ┌────────────┴────────────────┐
              |                              |
       [ Slash Command ]             [ Natural Language ]
       49 commands with              LangGraph ReAct Pipeline
       privacy tiers                         |
       (public/ephemeral/DM)    ┌────────────┴────────────┐
              |                 |                          |
              v          [ Sentinel ]              [ Image? ]
         Direct handler   Noise gate →             Vision Agent
                          drop or engage           Screenshot → diagnosis
                                |
                    ┌───────────┴───────────┐
                    |                       |
              [ DISMISS ]            [ ENGAGE ]
              Silent (0 API)               |
                              ┌────────────┼────────────┐
                              |            |            |
                          Knowledge    Replier +     ToolNode
                          Retrieval    bind_tools()  (5 tools)
                          (RAG)              |            |
                              |         Tool Response     |
                              |         Synthesis         |
                              └────────────┼────────────┘
                                           |
                                       [ Auditor ]
                                       Secret scrub
                                       Chakra guard
                                       SkillUp guard
                                       2000-char chunk
                                           |
                                    [ Discord Reply ]
                                    (ephemeral if personal)
```

### Core Pipeline — 6-Node LangGraph StateGraph

| Node | Role |
|---|---|
| **Sentinel** | Sub-millisecond regex noise gate + LLM fallback classifier. Pure greetings silently dropped with zero API waste. |
| **Knowledge** | Vector-less RAG — YAML knowledge tree + chunked markdown retrieval with token-overlap scoring from 4 reference documents. |
| **Replier** | Jinja2-templated system prompt with conversation history + tool binding via `ChatOpenAI.bind_tools()`. |
| **ToolNode** | Autonomous execution of 5 `@tool` functions — ticket creation, reward calculation, handbook search, profile lookup. |
| **Tool Response** | Synthesizes tool execution results into natural language. |
| **Auditor** | Secret scrubbing (IPs, tokens, paths), Chakra tab guard, SkillUp hosting guard, markdown-aware 2000-char chunking. |

### 7 Operational Rubrics

1. **Noise Gate** — Deterministic silent drop for casual banter (zero API waste, zero typing indicator)
2. **Direct Engagement** — Mentions and DMs always processed
3. **Platform Separation** — HRW vs HRC vs SkillUp boundaries, Chakra tab prohibition
4. **Reward Tiers** — `<300` vs `>=300` participant thresholds with exact package calculation
5. **Certificate Pipeline** — Canva CSV schema validation, bulk generation, and visual preview
6. **Escalation Router** — P0/P1/P2 severity classification with interactive DM dispatch to leads
7. **Safety Guardrails** — Prompt injection filtering, Discord bot token scrubbing, PII never in public channels

### Enterprise Resilience & Failover

The agent is built to stay live even when individual backends drop. Three independent resilience layers wrap the hot path:

| Layer | Primary | Fallback | Behavior on primary failure |
|---|---|---|---|
| **LLM inference** | vLLM (`VLLM_BASE_URL`) | NVIDIA NIM / Ollama (`NIM_BASE_URL`) | `ResilientChatModel` proxy catches transport/API errors after retries, logs `[LLM FAILOVER]`, re-dispatches the identical request to the secondary engine. Both down → `LLMFailoverError`. Programming errors (typos, bad args) propagate immediately without a wasted fallback hop. |
| **Database** | PostgreSQL (`DATABASE_URL`) | Persistent SQLite (`data/hrcc.db`) | Strict 3s connect timeout (`PG_CONNECT_TIMEOUT`). On failure logs `[DB FAILOVER]`, flips to SQLite, and re-initializes the schema. All reads/writes degrade Postgres→SQLite at runtime so the Discord event loop never crashes. |
| **Vision / OCR** | vLLM multimodal | NIM vision → Ollama `llava` | Ordered endpoint chain; each hop is skipped on 400 (model lacks image support) or transport error, logging `[VISION FAILOVER]` until one succeeds. Empty completions are treated as a failed hop. |

**Vision triage** additionally applies a deterministic severity classifier on top of the model output, appending a banner for each detected signal — **Chakra tab (P0 security trigger)**, **HRW 404 / inactive contest**, and **proctoring/disqualification violations** — so the critical safety message is never lost to model variance.

**Automated contest lifecycle daemon** runs on a 5-minute cadence and drives three stage-gated reminders per event (deduplicated so each fires exactly once):

| Stage | Channel | Content |
|---|---|---|
| **T-24h** | Home support channel + DM | Pre-event checklist — HRW link test, +30 min buffer, Chakra prohibition, standby POCs |
| **T-1h** | DM | Live proctoring protocol, HRC fallback rule, escalation contacts (Sanskruti / Sreesanth) |
| **T+24h** | DM | Export raw CSV and run `/validate_contest` for certificate + rewards validation |

---

## Authentication & Access Control

Every interaction passes through a mandatory authentication gate. The bot only operates in server channels — private DMs are rejected.

### Registration Flow

```
Ambassador runs /register
    → Modal: enters HRW email
    → Bot queries HackerRank for Work API → finds matching user
    → "Is this you? [Name] from [Team]" → [Confirm] / [Not Me]
    → Profile created, HRW identity linked, all commands unlocked
```

### 5-Tier Role Hierarchy

| Role | Who | Access Level | How Assigned |
|---|---|---|---|
| **Owner** | Company admin | Full system access | `OWNER_DISCORD_ID` in .env |
| **Admin** | Program leads (3) | All commands + mod management | `POC_DISCORD_*` in .env |
| **Moderator** | Senior ambassadors | Lookup + ticket + activity views | `/admin_set_mod` by Admin |
| **Ambassador** | Verified users | All self-service commands | `/register` + HRW email verification |
| **Unregistered** | New joiners | 7 public knowledge commands only | Default until `/register` |

### Privacy Tiers

| Tier | Visibility | Commands |
|---|---|---|
| **Public** | Everyone sees | `/rules`, `/sop`, `/resources`, `/rewards`, `/onboard`, `/certs`, `/question_bank`, `/leaderboard`, `/collab_browse`, `/marketing`, `/showcase_feed`, `/calendar`, `/trends` |
| **Ephemeral** | Only the user sees | `/my_tests`, `/my_status`, `/test_status`, `/register`, `/escalate`, `/benchmark`, `/impact_report`, all admin/mod commands |
| **DM Only** | Private inbox | Winner emails, full event reports with PII, candidate score exports |

---

## Slash Commands (49)

### Public Knowledge (no registration required)

| Command | Description |
|---|---|
| `/register` | Verify your HRW identity to unlock all commands |
| `/rules [platform]` | Platform rules card with Chakra prohibition |
| `/sop [contest \| hackathon \| workshop]` | Interactive dropdown with pre/live/post-event checklists |
| `/resources` | Asset hub — brand kit, SOPs, templates, handbook links |
| `/rewards [participants]` | Instant reward tier calculation with merchandise eligibility |
| `/onboard` | Interactive 4-step welcome walkthrough |
| `/certs` | Certificate generation guide with Canva Bulk Create steps |

### Ambassador Self-Service (registration required)

| Command | Description |
|---|---|
| `/my_status` | Monthly compliance dashboard — tier, points, achievements, events, stage |
| `/my_tests` | Live HRW test dashboard — status, questions, lock state, duration |
| `/test_status [id]` | Real-time contest monitoring — candidates, scores, status breakdown |
| `/preflight [id]` | Deep test config validator via HRW API — questions, lock, draft, buffer |
| `/set_profile` | Set college, country, timezone (auto-resolves region) |
| `/set_stage [stage]` | Update event lifecycle (Planning → Setup → Outreach → Live → Rewards) |
| `/create_event` | AI-powered event wizard — modal → promotion timeline + setup checklist |
| `/submit_report` | Structured post-event report with winners, auto-awards points |
| `/validate_contest [csv]` | CSV validator → analytics + Canva CSV + cert preview PNG + auto-report |
| `/curate_contest [audience] [duration] [focus]` | AI-generated HRW contest blueprint |
| `/event_check [url]` | Pre-flight URL validator — Chakra/SkillUp detection, readiness checklist |
| `/marketing [event] [date] [time] [url]` | Multi-platform promo copy (Discord, WhatsApp, LinkedIn) |
| `/verify_emails [emails]` | Winner email format check + institutional domain flagging |
| `/escalate [lead]` | File a P0/P1/P2 ticket with interactive modal |
| `/ticket_status [code]` | Live escalation ticket status lookup |
| `/request_letter` | Institutional permission letter request → Program Manager |
| `/request_speaker` | Speaker/judge request with 14-day lead-time enforcement |
| `/onboard_quiz` | 5-question handbook quiz — +50 pts on pass |
| `/benchmark` | Visual progress bars: your stats vs global average |
| `/impact_report` | Shareable impact summary with LinkedIn copy-paste |
| `/question_bank [type] [page]` | Browse 9,549 HRW questions by type (code/mcq/fullstack) |

### International & Community

| Command | Description |
|---|---|
| `/leaderboard [global \| my_region \| my_country]` | Rankings across 3 geographic scopes |
| `/find_ambassador [country \| region] [query]` | Discover peers worldwide |
| `/collab_request` | Post cross-campus/cross-country collaboration proposal |
| `/collab_browse` | Browse open collaboration requests globally |
| `/showcase` | Share event highlights — name, participants, winner, takeaway |
| `/showcase_feed` | Browse recent event highlights worldwide |
| `/calendar` | View upcoming events from ambassadors globally |
| `/trends` | Global program analytics — countries, regions, tier distribution |

### Moderator Commands

| Command | Description |
|---|---|
| `/mod_lookup [user]` | View any ambassador's full profile + HRW link + events |
| `/mod_tickets` | View all open escalation tickets |
| `/mod_activity` | Regional activity summary — inactive ambassadors, open tickets |

### Admin / Lead Commands

| Command | Description |
|---|---|
| `/admin_stats` | Monthly operations dashboard — events, participants, tickets, MTTR |
| `/admin_points [user] [pts] [reason]` | Manually award/deduct points with audit trail |
| `/admin_set_mod [user]` | Grant moderator role |
| `/admin_revoke [user]` | Revoke moderator role |
| `/admin_tickets` | View all escalation tickets across categories |
| `/admin_export` | Export full ambassador database as CSV |
| `/admin_broadcast [message]` | DM announcement to all registered ambassadors |
| `/ambassador [user]` | Deep profile lookup — HRW link, events, tier, achievements |
| `/audit [limit]` | Chronological audit log — registrations, points, mod actions, escalations |

### Owner Commands

| Command | Description |
|---|---|
| `/owner_api_status` | HRW API health check — tests, users, questions count |

---

## Autonomous Agent Capabilities

### ReAct Tool Calling

The LLM autonomously invokes tools during natural language conversations:

| Tool | Action |
|---|---|
| `create_escalation_ticket` | Creates tickets in the database, returns HRCC-XXX code |
| `lookup_ticket_status` | Queries live ticket status and resolution notes |
| `calculate_reward_tier` | Exact reward calculation based on participant count |
| `search_handbook_knowledge` | Dynamic retrieval from 4 reference documents |
| `lookup_ambassador_profile` | Queries event history and stats for any ambassador |

### Vision / OCR Agent

When an ambassador uploads a screenshot (PNG/JPG/GIF/WEBP), the bot automatically:
1. Detects the image attachment
2. Sends it to the vLLM multimodal endpoint with base64 encoding
3. Identifies the platform (HRW/HRC/SkillUp)
4. Extracts error messages and HTTP status codes
5. Provides diagnostic guidance and recommended actions
6. Triggers Chakra tab safety alert if detected

### Proactive Automations

| Automation | Trigger |
|---|---|
| **Event Reminders** | T-72h (test link), T-24h (buffer/POC), T+24h (export CSV) — timezone-aware |
| **Weekly Lead Digest** | Every Sunday — monthly stats, ticket metrics, MTTR |
| **Monthly Compliance Nudge** | Days 20-25 — DMs inactive ambassadors with action links |
| **vLLM Health Probe** | Every 60s — keeps GPU KV-cache warm |
| **Knowledge Hot-Reload** | Every 5min — detects handbook file changes, reloads without restart |
| **Incident Storm Clustering** | 3+ matching error reports in 2min → single notice instead of flood |

### Post-Event Intelligence

On CSV upload, the agent automatically:
1. Validates and filters active participants (score > 0)
2. Calculates reward tier and merchandise eligibility
3. Computes score analytics — completion rate, difficulty curve, avg/min/max
4. Generates normalized Canva Bulk Create CSV (7-column schema)
5. Renders a certificate preview PNG of the #1 winner
6. Generates a copy-paste event report (DM with emails, channel without)
7. Awards gamification points (+100/contest, +150/300+ participants)
8. Checks and grants achievement badges
9. Logs the action to the audit trail

---

## HackerRank for Work API Integration

**Base:** `https://www.hackerrank.com/x/api/v3`
**Auth:** Bearer token via `HRW_API_KEY` in .env

| Endpoint | Used By | Data |
|---|---|---|
| `GET /tests` | `/my_tests`, `/preflight` | All workspace tests — ownership-filtered per ambassador |
| `GET /tests/{id}` | `/preflight`, `/test_status` | Test config, questions, sections, timing |
| `GET /tests/{id}/candidates` | `/test_status` | Live candidate scores, status, completion |
| `GET /questions` | `/question_bank` | 9,549 questions — type, score, duration |
| `GET /users` | `/register` | Email-based identity verification |

**Per-ambassador scoping:** Every API query filters by the `owner` field matching the ambassador's linked `hrw_user_id`. An ambassador can never see another ambassador's tests or candidates.

---

## International Gamification System

### Tier Progression

| Tier | Points | Badge |
|---|---|---|
| Apprentice Ambassador | 0 – 199 | 🎖️ |
| Campus Lead | 200 – 499 | 🥉 |
| National Fellow | 500 – 999 | 🥈 |
| Hall of Fame | 1000+ | 🥇 |

### Point Awards

| Action | Points |
|---|---|
| Contest hosted (CSV upload) | +100 |
| 300+ active participants | +150 |
| On-time report submitted | +50 |
| Onboarding quiz passed | +50 |
| Admin manual award | Variable |

### Achievement Badges

| Badge | Trigger |
|---|---|
| 🎯 First Event | Hosted first campus event |
| 🔥 300 Club | Reached 300+ active participants |
| 🏅 Decathlon | Hosted 10 contests |
| 🌍 Global Impact | Reached 1,000 total participants |
| ⚡ 5-Month Streak | Hosted events 5 consecutive months |
| 🤝 International Collaborator | Completed a cross-country collaboration |
| 🚨 P0 First Responder | Acknowledged a P0 emergency ticket |

### Leaderboards

3 geographic scopes powered by region mapping across 60+ countries:
- **Global** — top ambassadors worldwide
- **Region** — Asia-Pacific, EMEA, Americas
- **Country** — within your country

---

## Privacy & Security Model

| Layer | Mechanism |
|---|---|
| **DM Blocker** | Bot rejects all private DMs — only works in server channels |
| **Auth Gate** | Global `interaction_check` blocks unregistered users from gated commands |
| **Ephemeral Responses** | Personal data visible only to the requesting user |
| **PII via DM Only** | Winner emails and candidate scores never appear in public channels |
| **Ownership Filtering** | HRW API data scoped per ambassador via `hrw_links` table |
| **Secret Scrubbing** | IPs, server paths, Discord tokens, API keys redacted from all responses |
| **Prompt Injection Defense** | Regex detection for jailbreak attempts, neutral response |
| **Chakra Tab Guard** | Knowledge + auditor double-check blocks Chakra access recommendations |
| **Fail-Closed Admin Gate** | Empty admin list denies access (not grants) |
| **Audit Trail** | Every registration, point award, mod action, escalation, and CSV upload logged |

---

## Database Schema

Dual-backend: **PostgreSQL** (production) with **SQLite WAL** (fallback). Auto-migration on startup.

| Table | Purpose |
|---|---|
| `escalation_tickets` | P0/P1/P2 ticket lifecycle (PENDING → ACKNOWLEDGED → RESOLVED) |
| `ambassador_events` | Contest submissions — participants, rewards, CSV checksums |
| `ambassador_profiles` | College, country, region, timezone, lifecycle stage |
| `ambassador_points` | Gamification — points, tier, contest count by country/region |
| `points_ledger` | Append-only audit log of all point awards and achievements |
| `conversation_turns` | Persistent chat history surviving bot restarts |
| `collab_requests` | Cross-border collaboration proposals with status tracking |
| `hrw_links` | Discord ↔ HRW identity mapping (email-verified) |
| `moderators` | Moderator role grants with grantor tracking |
| `event_showcase` | Ambassador event highlights for community feed |
| `audit_log` | Full chronological trail — who did what, when, to whom |

---

## Prompt Architecture

Jinja2 template system with `FileSystemLoader` and `trim_blocks`:

| Template | Purpose |
|---|---|
| `system_message.jinja` | Core persona, handbook grounding, hard rules, escalation directory |
| `replier.jinja` | Extends system_message with tool docs, RAG context, escalation advisories |
| `sentinel_classifier.jinja` | Binary REPLY/NO_REPLY intent classifier |
| `contest_curator.jinja` | HRW contest blueprint — questions, scoring, proctoring, instructions |
| `marketing_copy.jinja` | Multi-platform promotional copy generator |
| `event_wizard.jinja` | Event planning prompt — timeline, setup, monitoring, post-event |
| `vision_analyzer.jinja` | Screenshot diagnostic — platform ID, error extraction, safety rules |

---

## Project Structure

```
hrcc_bot/
├── bot.py                              # Entry point — lifecycle, message handling, background tasks
├── README.md
├── CLAUDE.md
├── knowledge_data.yaml                 # Canonical handbook rules (YAML knowledge tree)
│
├── src/
│   ├── config.py                       # Pydantic Settings — all env vars
│   ├── auth_gate.py                    # 5-tier RBAC — role resolver, @require_role, gate check
│   ├── hrw_api.py                      # HackerRank for Work API v3 client
│   ├── graph.py                        # 6-node LangGraph ReAct pipeline
│   ├── tools.py                        # 5 @tool functions for autonomous actions
│   ├── llm_client.py                   # LangChain ChatOpenAI wrappers for vLLM
│   ├── knowledge.py                    # RAG retriever with hot-reload
│   ├── rubrics.py                      # 7-rubric classifier and safety engine
│   ├── vision.py                       # Multimodal screenshot analyzer
│   ├── db.py                           # Dual PostgreSQL/SQLite — 11 tables, migrations
│   ├── context.py                      # Persistent conversation memory (LRU + SQLite)
│   ├── csv_validator.py                # CSV/XLSX parser, Canva exporter, analytics, auto-report
│   ├── cert_generator.py               # Pillow-based certificate preview renderer
│   ├── escalation.py                   # Ticket creation + POC DM dispatch
│   ├── escalation_views.py             # Interactive buttons (Acknowledge/Reply/Resolve modals)
│   ├── incident_cluster.py             # Error storm deduplication engine
│   ├── scheduler.py                    # Reminders, weekly digest, compliance nudges
│   ├── slash_commands.py               # 49 slash commands across 5 role tiers
│   └── prompts/
│       ├── template_manager.py         # Jinja2 template engine (singleton)
│       └── templates/                  # 7 .jinja prompt files
│
├── references/                         # Official handbook, SOPs, templates, FAQs (4 docs)
├── tests/                              # 283 tests across 14 test files
├── deploy/
│   ├── deploy.sh                       # Automated pull → install → test → restart
│   ├── hrcc-bot.service                # Systemd service unit
│   ├── requirements.txt                # Pinned dependencies (14 packages)
│   └── .env.example                    # Full configuration template
├── data/                               # SQLite database (gitignored)
└── docs/                               # 13 architecture specs and design documents
```

---

## Setup & Deployment

```bash
# Clone and configure
git clone <repo-url> && cd hrcc_bot
python3 -m venv venv && source venv/bin/activate
pip install -r deploy/requirements.txt
cp deploy/.env.example .env
# Edit .env: DISCORD_BOT_TOKEN, HRW_API_KEY, OWNER_DISCORD_ID, POC IDs

# Run
python bot.py

# Test
DISCORD_BOT_TOKEN=test pytest tests/ -v

# Deploy (production)
chmod +x deploy/deploy.sh
./deploy/deploy.sh

# Systemd
sudo cp deploy/hrcc-bot.service /etc/systemd/system/
sudo systemctl enable --now hrcc-bot
```

### Required Environment Variables

| Variable | Purpose |
|---|---|
| `DISCORD_BOT_TOKEN` | Discord bot authentication |
| `VLLM_BASE_URL` | vLLM inference endpoint (OpenAI-compatible) |
| `VLLM_MODEL` | Model name for text generation |
| `HRW_API_KEY` | HackerRank for Work API v3 bearer token |
| `OWNER_DISCORD_ID` | Discord ID of the system owner |
| `POC_DISCORD_SANSKRUTI` | Program Manager Discord ID |
| `POC_DISCORD_SREESANTH` | Technical Lead Discord ID |
| `POC_DISCORD_NITISH` | Design Lead Discord ID |
| `DATABASE_URL` | PostgreSQL connection string (empty = SQLite fallback) |

---

## Tech Stack

| Layer | Technology |
|---|---|
| **Framework** | discord.py 2.3+ (async, slash commands, modals, buttons) |
| **Agent Orchestration** | LangGraph StateGraph with conditional edges + ToolNode |
| **LLM Interface** | LangChain ChatOpenAI → local vLLM (OpenAI-compatible) |
| **Vision** | vLLM multimodal endpoint with base64 image encoding |
| **Prompt Management** | Jinja2 templates (7 files) |
| **External API** | HackerRank for Work API v3 (tests, questions, users, candidates) |
| **Database** | PostgreSQL (psycopg3) / SQLite WAL (fallback) — 11 tables |
| **Certificate Rendering** | Pillow (PIL) — 1200x800 PNG |
| **Configuration** | Pydantic Settings v2 with .env |
| **Knowledge Base** | YAML + 4 Markdown docs with keyword-scored retrieval |
| **Spreadsheet Parsing** | csv + openpyxl (CSV and XLSX) |
| **Testing** | pytest — 283 tests across 14 files |
| **Deployment** | systemd + bash deploy script |
