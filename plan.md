# HackerRank Campus Crew Super Agent (`hrcc_bot`) — Architecture & Implementation Plan

## 1. Executive Summary & Objective
The **HackerRank Campus Crew Super Agent (`hrcc_bot`)** is a purpose-built, high-performance, production-grade Discord assistant engineered specifically for the HackerRank Campus Crew ambassador ecosystem.

Rather than relying on heavy autonomous frameworks (such as Hermes/OpenClaw) that carry bloat, auto-threading side effects, and silence-rejection errors, `hrcc_bot` is a **modular, multi-rubric native Python agent**. It interfaces directly with the local high-throughput **vLLM** inference engine (`neuralmagic/Meta-Llama-3.1-8B-Instruct-FP8`) hosted on the `ai-server` (`10.1.53.27`).

---

## 2. Multi-Rubric Operational Matrix

The Super Agent operates across **7 primary rubrics** to ensure zero false-positive spam while delivering expert, deterministic operational guidance:

```
                                  [ Inbound Discord Event ]
                                              │
                         ┌────────────────────┴────────────────────┐
                         ▼                                         ▼
                 [ Direct Mention / DM ]                  [ Public Channel Message ]
                         │                                         │
                         ▼                                         ▼
               [ Direct Response Lane ]                 [ Rubric 1: Noise & Chatter Gate ]
                         │                                         │
                         │                           ┌─────────────┴─────────────┐
                         │                           ▼                           ▼
                         │                     [ Casual Chatter ]       [ Campus Crew Intent ]
                         │                           │                           │
                         │                           ▼                           │
                         │                     [ NO_REPLY ]                      │
                         │                   (Silent Drop: 0 API)                │
                         │                                                       │
                         └───────────────────────────┬───────────────────────────┘
                                                     ▼
                                       [ Multi-Rubric Context Engine ]
                                                     │
               ┌───────────────────────┬─────────────┴─────────────┬───────────────────────┐
               ▼                       ▼                           ▼                       ▼
    [ Rubric 3: Platform & SOP ] [ Rubric 4: Rewards ] [ Rubric 5: Certs ] [ Rubric 6: Escalation ]
    • HRW vs HRC vs SkillUp      • <300 vs >=300       • Canva CSV schema  • Sanskruti (Ops/Prizes)
    • Strict "Chakra" boundary   • Infinity Plan       • Code submission   • Sreesanth (Tech/HRW)
    • Buffer time & links        • Merch activation      verification      • Nitish (Design/Brand)
               └───────────────────────┼───────────────────────────┴───────────────────────┘
                                       ▼
                       [ Rubric 7: Safety & Guardrails ]
                       • Prompt injection scrubbing
                       • Token & path redaction
                       • 2000-char Discord chunking
                                       │
                                       ▼
                        [ Deterministic Channel Dispatch ]
```

### Rubric Breakdown
| Rubric ID | Name | Trigger Conditions | Behavioral Action |
| :--- | :--- | :--- | :--- |
| **Rubric 1** | **Noise & Banter Filter** | Casual greetings between users ("hi", "gm", "machi"), cross-talk, memes, bot-to-bot chats. | **Deterministic SILENT drop (`NO_REPLY`)**. Zero Discord API sends, typing canceled immediately. |
| **Rubric 2** | **Direct Engagement** | Explicit `@bot` mention, direct reply to a bot message, or Direct Message (DM). | **Full Context Engagement**. Answers query or explains bot's purpose if greeting. |
| **Rubric 3** | **Platform & SOP Guidance** | Inquiries about HRW, HRC, SkillUp, test creation, contest URLs, buffer time, proctoring. | Provides exact step-by-step SOPs. Strictly enforces: **Never touch Chakra tab**. |
| **Rubric 4** | **Reward Tiers & Activation** | Questions on prizes, participant counts, Infinity plan, AI tools, swag. | Enforces thresholds: `<300` (Infinity + AI tools + Mock) vs `>=300` (+ Official Merch). Instructs winner email submission format. |
| **Rubric 5** | **Certificate Pipeline** | Queries on attendee certificates, generation, verification. | Outlines Canva Bulk Create via CSV (Full Name, Email, Rank, Score). Clarifies only code submitters qualify. |
| **Rubric 6** | **Lead Escalation Directory** | Platform outages, HRW permissions, prize delivery delays, speaker requests. | Routes to exact lead: **Sanskruti** (Rewards/Speakers), **Sreesanth** (Platform/HRW), **Nitish** (Design). |
| **Rubric 7** | **Security & Guardrails** | System prompt probing, jailbreak attempts, unapproved sponsorship promises. | Refuses jailbreaks, sanitizes internal tokens/IPs, never promises unauthorized sponsorships. |

---

## 3. Multi-Agent Orchestration & Vector-less RAG Overview

The Super Agent implements a **decoupled 4-tier multi-agent pipeline** (see full deep dive in [`MULTI_AGENT_ORCHESTRATION.md`](file:///data/production/hrcc_bot/MULTI_AGENT_ORCHESTRATION.md)):

```
[ Inbound Discord Event ]
           │
           ▼
┌─────────────────────────────────────────────────────────────┐
│ 1. SENTINEL AGENT (Gatekeeper & Triage)                     │
│    • Reads ALL messages in monitored channels               │
│    • Evaluates whether to reply or drop                     │
│    • Output: Structured Verdict (DISMISS vs ENGAGE)         │
└──────────────┬──────────────────────────────────────────────┘
               │
       ┌───────┴────────────────────────┐
       ▼ (DISMISS)                      ▼ (ENGAGE)
┌──────────────┐        ┌─────────────────────────────────────┐
│ SILENT DROP  │        │ 2. VECTOR-LESS RAG ENGINE           │
│ (0 API Sends)│        │    • Zero vector DB / embeddings    │
│              │        │    • Hierarchical Knowledge Tree    │
│              │        │    • Deterministic snippet lookup   │
└──────────────┘        └─────────────────┬───────────────────┘
                                          │
                                          ▼
                        ┌─────────────────────────────────────┐
                        │ 3. REPLIER AGENT (Generator)        │
                        │    • Synthesizes verified answer    │
                        │    • Tailored to ambassador persona │
                        └─────────────────┬───────────────────┘
                                          │
                                          ▼
                        ┌─────────────────────────────────────┐
                        │ 4. AUDITOR AGENT (Safety & Critic)  │
                        │    • Chakra tab boundary check      │
                        │    • Secret & token scrubbing       │
                        │    • Markdown 2000-char validation  │
                        └─────────────────┬───────────────────┘
                                          │
                                          ▼
                        [ Discord Inline Dispatch ]
```

### Why Vector-less RAG?
Rather than using heavy vector databases (Milvus, Chroma, Pinecone) that suffer from semantic drift, high compute overhead, and cosine similarity confusion between inverted rules (e.g., HRW vs SkillUp, or `<300` vs `≥300` rewards), `hrcc_bot` uses a **Hierarchical Knowledge Tree**. It performs deterministic in-memory key lookups (<0.1ms) with exact numerical threshold evaluation.

---

## 4. Modular System Architecture

The project is structured under `/data/production/hrcc_bot/` with clean role separation:

```
/data/production/hrcc_bot/
├── config.py                 # Pydantic-based configuration (vLLM URL, token, channel IDs, thresholds)
├── main.py                   # Async entrypoint, lifecycle management, graceful shutdown
├── bot/
│   ├── __init__.py
│   ├── client.py             # discord.Client subclass with custom intents & lifecycle hooks
│   └── handlers.py           # Inbound message pipeline: normalize -> sentinel -> rag -> replier -> auditor
├── core/
│   ├── __init__.py
│   ├── sentinel.py           # Sentinel Agent: regex pre-screener + LLM classification router
│   ├── orchestrator.py       # Multi-agent state machine & async coordination
│   ├── replier.py            # Replier Agent: prompt synthesis & vLLM client
│   └── auditor.py            # Auditor Agent: safety critic, Chakra filter & secret redactor
├── rag/
│   ├── __init__.py
│   ├── tree.py               # Hierarchical Knowledge Graph data structure
│   ├── extractor.py          # Deterministic keyword & numerical condition router
│   └── knowledge_data.yaml   # Canonical, validated handbook rules
├── guards/
│   ├── __init__.py
│   ├── security.py           # Prompt injection sanitizer, Chakra tab alert, secret scrubber
│   └── chunker.py            # Markdown-aware 2000-character message splitter
├── utils/
│   ├── __init__.py
│   ├── logger.py             # Rotating JSON & console logger with colored output
│   └── metrics.py            # Prometheus-compatible internal telemetry (latency, silences, turns)
├── deploy/
│   ├── hrcc-bot.service      # Systemd service unit definition for ai-server
│   ├── deploy.sh             # Automated rsync & systemctl deployment script
│   └── requirements.txt      # Minimal pinned dependencies (discord.py, httpx, pydantic, etc.)
└── docs/
    ├── plan.md               # Master plan (this document)
    ├── MULTI_AGENT_ORCHESTRATION.md # Multi-agent pipeline & Vector-less RAG specification
    ├── ESCALATION_ROUTER.md  # Autonomous escalation dispatcher & bi-directional POC DM relay
    ├── SUPPORT_SYSTEMS.md    # Ticket lifecycle, event pre-flight validator, incident storm clustering
    ├── AMBASSADOR_OPERATIONS.md # Ambassador onboarding walkthrough, resource hub, permission letters
    ├── ADVANCED_SERVICES.md  # CSV validator, slash commands, vision agent, temporal reminders
    ├── RUBRICS.md            # Intent classification matrix & test vectors
    ├── HANDBOOK_REFERENCE.md # Official Ambassador Handbook knowledge base
    ├── EDGE_CASES.md         # Technical hardening & edge-case mitigations
    └── DEPLOYMENT.md         # Production deployment & operations guide
```

---

## 5. Detailed Component Design

### 5.1. Sentinel Agent (`core/sentinel.py`)
- **Stage 1 (Sub-millisecond Pre-filter):**
  - Messages from bots $\rightarrow$ Ignored.
  - Direct @mention of bot $\rightarrow$ Instant PASS (`ENGAGE`).
  - Common pure greetings between humans ("hi", "hey", "sup", "bro", "gm", "gn", "machi") with no Campus Crew keywords $\rightarrow$ Instant **SILENT DROP** (`DISMISS`).
- **Stage 2 (LLM Contextual Classification):**
  - For ambiguous messages in monitored channels, a lightweight classification prompt evaluates if the message relates to:
    `[CAMPUS_CREW_QUERY, GENERAL_OFFTOPIC, CASUAL_BANTER]`
  - If `GENERAL_OFFTOPIC` or `CASUAL_BANTER` $\rightarrow$ Return `NO_REPLY` (`DISMISS`).

### 5.2. Vector-less RAG Engine (`rag/`)
- Pure in-memory dictionary and Trie lookup mapping `domain_keys` to exact canonical text blocks.
- Hardcoded numerical threshold logic for participant count evaluations.
- Instant (<0.1ms) retrieval latency with 0% chance of embedding drift.

### 5.3. High-Performance Inference Engine (`core/engine.py`)
- Uses `httpx.AsyncClient` with connection pooling (`limits=httpx.Limits(max_keepalive_connections=20, max_connections=50)`).
- Calls local vLLM at `http://127.0.0.1:8000/v1/chat/completions`.
- Supports streaming for low time-to-first-token, but collects output before sending to avoid Discord rate limits.
- Temperature: `0.1` for factual handbook queries; `0.0` for classification.

### 4.3. Edge Case Mitigation & Hardening (`guards/`)
1. **Discord 2000-Character Barrier (`guards/chunker.py`):**
   - Splits long responses strictly on paragraph breaks (`\n\n`) or sentence boundaries.
   - Automatically re-balances unclosed markdown code blocks (e.g. ` ```python `) across chunks.
2. **Deterministic Inline Delivery (No Threads):**
   - Directly calls `channel.send(content, reference=message, mention_author=False)`.
   - Never calls `create_thread()` or `message.channel.create_thread()`.
3. **Typing Indicator Management:**
   - Uses `async with channel.typing():` inside a wrapped background task.
   - If the bot decides to output `NO_REPLY`, typing is immediately aborted before any message is sent.
4. **vLLM Failover / Backoff:**
   - If vLLM is restarting or busy, retries up to 3 times with exponential backoff (0.5s, 1s, 2s).
   - If still unreachable, outputs a polite temporary service alert rather than crashing.

---

## 5. Deployment & Migration Strategy to `ai-server`

1. **Local Assembly & Testing:**
   - Develop and test full code package inside `/data/production/hrcc_bot/`.
   - Verify all unit tests (classification, chunking, prompts, knowledge retrieval).
2. **Target Setup on `ai-server` (`10.1.53.27`):**
   - Target Directory: `/home/ai-server/hrcc_bot`.
   - Virtualenv: `/home/ai-server/hrcc_bot/.venv` with `discord.py` and `httpx`.
   - Stop & disable `hermes-gateway.service`.
   - Install & enable `hrcc-bot.service`.
3. **Monitoring & Health Checks:**
   - `systemctl status hrcc-bot.service`
   - Real-time journal logs: `journalctl -u hrcc-bot.service -f`
   - vLLM load verification via `curl http://127.0.0.1:8000/v1/models`.

---

## 6. Execution Roadmap
- [x] **Phase 1:** Architectural specification and multi-rubric blueprint (`plan.md`).
- [ ] **Phase 2:** Core implementation (configuration, knowledge base, prompts, guards, chunker).
- [ ] **Phase 3:** Bot engine & Discord pipeline (ingress, classifier, vLLM client, dispatcher).
- [ ] **Phase 4:** Testing & validation suite (test edge cases, classification accuracy, chunking).
- [ ] **Phase 5:** Deployment to `ai-server`, systemd service migration, and live verification.
