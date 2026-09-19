# HackerRank Campus Crew Super Agent

An autonomous, production-grade Discord agent for the **HackerRank Campus Crew** global ambassador program. Built with **LangGraph**, **LangChain**, and **discord.py**, powered by local **vLLM** inference.

The agent handles the entire ambassador lifecycle — from onboarding and event planning through contest validation, reward activation, and post-event reporting — while enforcing strict operational boundaries defined in the official Ambassador Handbook.

---

## Architecture

```
                              [ Inbound Discord Message ]
                                         |
                    +--------------------+--------------------+
                    |                                         |
            [ Direct Mention / DM ]                [ Public Channel ]
                    |                                         |
                    v                                         v
          [ Direct Engage ]                    [ Rubric 1: Noise Gate ]
                    |                           Regex + LLM classifier
                    |                                  |
                    |                     +------------+------------+
                    |                     |                         |
                    |              [ NO_REPLY ]              [ ENGAGE ]
                    |            Silent drop (0 API)               |
                    |                                              |
                    +-------------------+--------------------------+
                                        |
                                        v
                          [ LangGraph ReAct Pipeline ]
                                        |
              +------------+------------+------------+------------+
              |            |            |            |            |
          Knowledge    Replier      ToolNode    Tool Response  Auditor
          Retrieval   (vLLM +       (5 tools)   Synthesis     Safety +
          (RAG)       bind_tools)                              Chunker
                                        |
                                        v
                          [ Discord Inline Reply ]
                         (mention_author=False)
```

### Core Pipeline (6-Node LangGraph StateGraph)

| Node | Role |
|---|---|
| **Sentinel** | Sub-millisecond regex noise gate + LLM fallback classifier. Pure greetings silently dropped. |
| **Knowledge** | Vector-less RAG — YAML knowledge tree + chunked markdown retrieval with token-overlap scoring. |
| **Replier** | Jinja2-templated system prompt + conversation history + tool binding via `ChatOpenAI.bind_tools()`. |
| **ToolNode** | Autonomous execution of 5 `@tool` functions (ticket creation, reward calc, handbook search, etc.). |
| **Tool Response** | Synthesizes tool outputs into a natural language response. |
| **Auditor** | Secret scrubbing, Chakra tab guard, SkillUp hosting guard, 2000-char markdown-aware chunking. |

### 7 Operational Rubrics

1. **Noise Gate** — Deterministic silent drop for casual banter (zero API waste)
2. **Direct Engagement** — Mentions and DMs always processed
3. **Platform Separation** — HRW vs HRC vs SkillUp boundaries, Chakra tab prohibition
4. **Reward Tiers** — `<300` vs `>=300` participant thresholds with exact package calculation
5. **Certificate Pipeline** — Canva CSV schema validation and bulk certificate generation
6. **Escalation Router** — P0/P1/P2 severity classification with interactive DM dispatch
7. **Safety Guardrails** — Prompt injection filtering, token/IP/path redaction, Discord bot token scrubbing

---

## Slash Commands (24)

### Ambassador Self-Service
| Command | Description |
|---|---|
| `/onboard` | Interactive welcome walkthrough for new ambassadors |
| `/set_profile` | Set college, country, timezone (auto-resolves region from 60+ countries) |
| `/set_stage` | Update event lifecycle stage (Planning → Setup → Outreach → Live → Rewards) |
| `/my_status` | Monthly compliance dashboard with tier badge, points, achievements, events |
| `/resources` | Asset hub — brand kit, SOPs, templates, handbook links |
| `/rewards [participants]` | Instant reward tier calculation with merchandise eligibility |
| `/sop [event_type]` | Interactive dropdown with pre/live/post-event checklists |
| `/certs` | Certificate generation guide with Canva Bulk Create steps |
| `/marketing [event] [date] [time] [url]` | Multi-platform promo copy (Discord, WhatsApp, LinkedIn) |
| `/rules [platform]` | Platform rules card with Chakra prohibition warning |
| `/event_check [url]` | Pre-flight URL validator — Chakra/SkillUp detection, readiness checklist |
| `/verify_emails [emails]` | Winner email format check + institutional domain flagging |
| `/validate_contest [csv]` | CSV validator → Canva certificate CSV + winner embed + cert preview PNG |

### Escalation & Support
| Command | Description |
|---|---|
| `/escalate [lead]` | Modal for issue description, auto-creates P0/P1/P2 ticket, routes to POC DMs |
| `/ticket_status [code]` | Live status lookup for escalation tickets |
| `/request_letter` | Institutional permission letter request → Program Manager |
| `/request_speaker` | Speaker/judge request with 14-day lead-time enforcement |

### Gamification & Leaderboards
| Command | Description |
|---|---|
| `/leaderboard [scope]` | Global, regional (Asia-Pacific/EMEA/Americas), or country rankings |
| `/find_ambassador [scope] [query]` | Discover ambassadors by country or region |
| `/collab_request` | Post cross-campus/cross-country collaboration proposals |
| `/collab_browse` | Browse open collaboration requests worldwide |

### AI-Powered Tools
| Command | Description |
|---|---|
| `/curate_contest [audience] [duration] [focus]` | AI-generated HRW contest blueprint with question distribution, scoring, proctoring settings |

### Lead Operations (Restricted)
| Command | Description |
|---|---|
| `/admin_stats` | Monthly dashboard — events, participants, tickets, MTTR (lead-only) |
| `/ambassador [user]` | Profile + event history + tier badge for any ambassador |

---

## Autonomous Agent Capabilities

### ReAct Tool Calling
The LLM can autonomously invoke 5 tools during conversation:
- **create_escalation_ticket** — Creates tickets in SQLite/Postgres and returns the HRCC-XXX code
- **lookup_ticket_status** — Queries live ticket status and resolution notes
- **calculate_reward_tier** — Exact reward calculation based on participant count
- **search_handbook_knowledge** — Dynamic retrieval from 4 reference documents
- **lookup_ambassador_profile** — Queries event history and stats for any ambassador

### Proactive Automations
- **Event Reminders** — T-72h, T-24h, T+24h DMs with action checklists
- **Weekly Lead Digest** — Sunday DM to program leads with monthly stats and ticket metrics
- **Monthly Compliance Nudge** — DMs inactive ambassadors between 20th-25th of each month
- **vLLM Health Probe** — 60-second canary ping keeping GPU KV-cache warm
- **Knowledge Hot-Reload** — File mtime monitoring, auto-reloads handbook changes without restart

### Incident Storm Clustering
When 3+ users report the same platform error within 2 minutes, collapses into a single incident notice instead of flooding lead DMs.

### Achievement Badges
Automatically granted on milestones:
| Badge | Trigger |
|---|---|
| First Event | Hosted first campus event |
| 300 Club | Reached 300+ active participants |
| Decathlon | Hosted 10 contests |
| Global Impact | Reached 1,000 total participants |
| International Collaborator | Completed a cross-country collaboration |
| P0 First Responder | Triaged an emergency ticket |
| 5-Month Streak | Hosted events 5 consecutive months |

### Post-Event Intelligence
On CSV upload, the agent automatically:
1. Validates and filters active participants (score > 0)
2. Calculates reward tier and merchandise eligibility
3. Generates normalized Canva Bulk Create CSV (7-column schema)
4. Renders a certificate preview PNG of the #1 winner
5. Generates a copy-paste event report formatted for the Program Manager
6. Awards gamification points (+100/contest, +150/300+ participants)
7. Checks and grants achievement badges

---

## Database

Dual-backend: **PostgreSQL** (production) with **SQLite WAL** (fallback/development).

| Table | Purpose |
|---|---|
| `escalation_tickets` | Ticket lifecycle (PENDING → ACKNOWLEDGED → RESOLVED) with P0/P1/P2 severity |
| `ambassador_events` | Contest submissions with participant counts, reward tiers, CSV checksums |
| `ambassador_profiles` | College, country, region, timezone, lifecycle stage |
| `ambassador_points` | Gamification — total points, tier name, contest count, merch events |
| `points_ledger` | Append-only audit log of all point awards and achievement grants |
| `conversation_turns` | Persistent chat history surviving bot restarts |
| `collab_requests` | Cross-campus collaboration proposals with status tracking |

Auto-migration on startup via `ALTER TABLE ADD COLUMN` for existing databases.

---

## Prompt Architecture

Jinja2 template system (modeled on `interviewstreet/hiring-agent`):

| Template | Purpose |
|---|---|
| `system_message.jinja` | Core persona, handbook grounding, hard rules, escalation directory |
| `replier.jinja` | Extends system_message with tool docs, RAG context, escalation advisories |
| `sentinel_classifier.jinja` | Binary REPLY/NO_REPLY intent classifier |
| `contest_curator.jinja` | HRW contest blueprint generation prompt |
| `marketing_copy.jinja` | Multi-platform promotional copy generator |

---

## Project Structure

```
hrcc_bot/
├── bot.py                          # Discord bot entry point with lifecycle management
├── README.md
├── CLAUDE.md
├── knowledge_data.yaml             # Canonical handbook rules (YAML knowledge tree)
├── src/
│   ├── config.py                   # Pydantic-settings configuration
│   ├── llm_client.py               # LangChain ChatOpenAI wrappers for vLLM
│   ├── graph.py                    # 6-node LangGraph ReAct pipeline
│   ├── tools.py                    # 5 @tool functions for autonomous actions
│   ├── knowledge.py                # RAG retriever with hot-reload
│   ├── rubrics.py                  # 7-rubric classifier and safety engine
│   ├── db.py                       # Dual SQLite/Postgres database layer
│   ├── context.py                  # Persistent conversation memory (LRU + SQLite)
│   ├── csv_validator.py            # Contest CSV parser + Canva exporter + auto-report
│   ├── cert_generator.py           # Pillow-based certificate preview renderer
│   ├── escalation.py               # Ticket creation + POC DM dispatch
│   ├── escalation_views.py         # Interactive buttons (Acknowledge/Reply/Resolve)
│   ├── incident_cluster.py         # Error storm deduplication engine
│   ├── scheduler.py                # Background tasks (reminders, digest, compliance)
│   ├── slash_commands.py           # 24 slash commands
│   └── prompts/
│       ├── template_manager.py     # Jinja2 template engine
│       └── templates/              # 5 .jinja prompt files
├── references/                     # Official handbook, SOPs, templates, FAQs
├── tests/                          # 230 tests across 10 test files
├── deploy/
│   ├── deploy.sh                   # Automated pull → install → test → restart
│   ├── hrcc-bot.service            # Systemd service unit
│   ├── requirements.txt            # Pinned dependencies
│   └── .env.example                # Environment configuration template
├── data/                           # SQLite database (gitignored)
└── docs/                           # Architecture specs and design documents
```

---

## Setup

```bash
# Clone and configure
git clone <repo-url> && cd hrcc_bot
python3 -m venv venv && source venv/bin/activate
pip install -r deploy/requirements.txt
cp deploy/.env.example .env
# Edit .env with your Discord bot token and vLLM endpoint

# Run
python bot.py

# Test
DISCORD_BOT_TOKEN=test pytest tests/ -v

# Deploy (production)
chmod +x deploy/deploy.sh
./deploy/deploy.sh
```

---

## Tech Stack

| Layer | Technology |
|---|---|
| **Framework** | discord.py 2.3+ (async) |
| **Agent Orchestration** | LangGraph (StateGraph with conditional edges + ToolNode) |
| **LLM Interface** | LangChain ChatOpenAI → local vLLM (OpenAI-compatible API) |
| **Prompt Management** | Jinja2 templates |
| **Database** | PostgreSQL (psycopg3) / SQLite WAL (fallback) |
| **Certificate Rendering** | Pillow (PIL) |
| **Configuration** | Pydantic Settings v2 |
| **Knowledge Base** | YAML + Markdown with keyword-scored retrieval |
| **Spreadsheet Parsing** | csv + openpyxl |
| **Testing** | pytest (230 tests) |
