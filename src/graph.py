from __future__ import annotations

import logging
import re
import time
from typing import Any, TypedDict

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langgraph.graph import END, StateGraph
from langgraph.graph.state import CompiledStateGraph

from src.knowledge import build_context_block, get_reward_tier
from src.llm_client import get_classifier_llm, get_llm
from src.rubrics import (
    chunk_message,
    contains_chakra_reference,
    detect_escalation_target,
    extract_participant_count,
    has_campus_crew_intent,
    is_injection_attempt,
    is_noise,
    scrub_secrets,
)

log = logging.getLogger("hrcc.graph")

_SKILLUP_HOST_RE = re.compile(
    r"(host|run|conduct|organize|hold).{0,40}(skillup|skill\s*up)"
    r"|use\s+(skillup|skill\s*up)\s+.{0,30}(event|contest|hackathon|test|workshop)",
    re.IGNORECASE,
)


class PipelineState(TypedDict, total=False):
    message_content: str
    author_name: str
    author_id: int
    channel_id: int
    is_dm: bool
    is_mention: bool
    is_bot: bool
    conversation_history: list[dict[str, str]]

    verdict: str
    knowledge_context: str
    raw_response: str
    final_chunks: list[str]
    escalation_target: str | None
    error: str | None
    _t0: float
    latency_ms: float


# ---------------------------------------------------------------------------
# Node 1: Sentinel — Gatekeeper & Triage
# ---------------------------------------------------------------------------

CLASSIFIER_SYSTEM_PROMPT = (
    "You are an intent classifier for a HackerRank Campus Crew Discord server. "
    "Evaluate the user's message and decide whether it relates to campus coding events, "
    "the HackerRank platform (HRW, HRC, SkillUp), ambassador operations, rewards, "
    "certificates, or technical support.\n\n"
    "Respond with EXACTLY one word:\n"
    "- REPLY — if the message is a campus crew / HackerRank related query\n"
    "- NO_REPLY — if the message is casual banter, off-topic, or unrelated\n\n"
    "Output only REPLY or NO_REPLY. Nothing else."
)


async def sentinel_node(state: PipelineState) -> dict[str, Any]:
    t0 = time.monotonic()

    if state.get("is_bot"):
        return {"verdict": "DISMISS", "_t0": t0}

    if state.get("is_dm") or state.get("is_mention"):
        return {"verdict": "ENGAGE", "_t0": t0}

    text = state["message_content"].strip()

    if is_noise(text):
        log.debug("Sentinel: noise gate caught '%s'", text[:60])
        return {"verdict": "DISMISS", "_t0": t0}

    if has_campus_crew_intent(text):
        return {"verdict": "ENGAGE", "_t0": t0}

    try:
        classifier = get_classifier_llm()
        result = await classifier.ainvoke([
            SystemMessage(content=CLASSIFIER_SYSTEM_PROMPT),
            HumanMessage(content=text),
        ])
        decision = result.content.strip().upper()
        if "REPLY" in decision and "NO_REPLY" not in decision:
            return {"verdict": "ENGAGE", "_t0": t0}
        return {"verdict": "DISMISS", "_t0": t0}
    except Exception:
        log.exception("Sentinel LLM classification failed, defaulting to DISMISS")
        return {"verdict": "DISMISS", "_t0": t0}


# ---------------------------------------------------------------------------
# Node 2: Knowledge Retrieval (Vector-less RAG)
# ---------------------------------------------------------------------------

async def knowledge_node(state: PipelineState) -> dict[str, Any]:
    text = state["message_content"]
    context_parts: list[str] = [build_context_block(query=text)]

    count = extract_participant_count(text)
    if count is not None:
        tier = get_reward_tier(count)
        threshold = tier.get("threshold", "")
        packages = tier.get("winner_package", [])
        has_merch = tier.get("merchandise_included", False)
        context_parts.append(
            f"\n## Reward Lookup Result for {count} participants ({threshold})\n"
            f"Winner Package: {', '.join(packages)}\n"
            f"Merchandise Included: {'Yes' if has_merch else 'No'}"
        )

    if contains_chakra_reference(text):
        context_parts.append(
            "\n## CRITICAL SAFETY ALERT\n"
            "The Chakra tab is STRICTLY INTERNAL to HackerRank enterprise staff. "
            "Ambassadors must NEVER access, click, or trigger anything via Chakra. "
            "For mock interviews, advise requesting mock interview vouchers from Sanskruti (Program Manager)."
        )

    if _SKILLUP_HOST_RE.search(text):
        context_parts.append(
            "\n## CRITICAL PLATFORM RULE\n"
            "SkillUp (hackerrank.com/skillup) is STRICTLY for self-paced student learning. "
            "It must NEVER be used to host campus events, coding contests, or hackathons. "
            "Use HRW or HRC instead."
        )

    escalation = detect_escalation_target(text)

    return {
        "knowledge_context": "\n".join(context_parts),
        "escalation_target": escalation,
    }


# ---------------------------------------------------------------------------
# Node 3: Replier — Response Generation
# ---------------------------------------------------------------------------

REPLIER_SYSTEM_PROMPT = """\
You are the HackerRank Campus Crew Support Bot, an expert assistant for student ambassadors \
running campus coding events (contests, hackathons, workshops, tech talks).

You are grounded in the official Ambassador Handbook. Never hallucinate rewards, sponsorships, \
or speakers that are not in the handbook. Never promise anything not covered in the knowledge base.

HARD RULES:
- The Chakra tab inside HRW is STRICTLY INTERNAL. Ambassadors must NEVER access it.
- SkillUp is for self-paced learning ONLY. Never recommend it for hosting events.
- Never promise merchandise for events with fewer than 300 active participants.
- Active participants = those who submitted code/answers, NOT mere registrations.
- If a question requires escalation, direct the ambassador to the appropriate lead.

Respond in a helpful, concise, professional tone. Use markdown formatting. \
Keep responses under 1800 characters when possible.

--- KNOWLEDGE BASE ---
{knowledge_context}
"""


async def replier_node(state: PipelineState) -> dict[str, Any]:
    text = state["message_content"]
    context = state.get("knowledge_context", "")

    system_prompt = REPLIER_SYSTEM_PROMPT.format(knowledge_context=context)

    if is_injection_attempt(text):
        return {
            "raw_response": (
                "I'm the HackerRank Campus Crew Support Bot. "
                "I can help you with campus event organization, platform guidance, "
                "rewards information, and certificate generation. "
                "How can I assist you today?"
            )
        }

    escalation = state.get("escalation_target")
    if escalation:
        system_prompt += (
            f"\n\nNote: Based on the ambassador's query, this may need escalation to "
            f"the appropriate lead ({escalation.title()}). Include escalation guidance in your response."
        )

    messages: list[SystemMessage | HumanMessage | AIMessage] = [
        SystemMessage(content=system_prompt),
    ]

    for entry in state.get("conversation_history") or []:
        role = entry.get("role", "")
        content = entry.get("content", "")
        if not content:
            continue
        if role == "assistant":
            messages.append(AIMessage(content=content))
        else:
            messages.append(HumanMessage(content=content))

    messages.append(HumanMessage(content=text))

    try:
        llm = get_llm()
        result = await llm.ainvoke(messages)
        return {"raw_response": result.content.strip()}
    except Exception as exc:
        log.exception("Replier LLM call failed")
        return {
            "raw_response": (
                "I'm temporarily unable to process your request due to a backend issue. "
                "Please try again in a moment, or reach out directly to the Campus Crew leads."
            ),
            "error": str(exc),
        }


# ---------------------------------------------------------------------------
# Node 4: Auditor — Safety Critic & Formatter
# ---------------------------------------------------------------------------

async def auditor_node(state: PipelineState) -> dict[str, Any]:
    response = state.get("raw_response", "")
    user_text = state["message_content"]

    response = scrub_secrets(response)

    # Chakra guard
    if contains_chakra_reference(user_text):
        resp_lower = response.lower()
        if "chakra" in resp_lower and "access" in resp_lower:
            if not any(w in resp_lower for w in ("never", "must not", "do not", "don't", "strictly")):
                response = (
                    "**Important:** The **Chakra** tab in HackerRank for Work is strictly internal "
                    "to HackerRank staff. As an ambassador, you must **never** access or click on it.\n\n"
                    "If you need mock interview features, please request mock interview vouchers "
                    "from **Sanskruti (Program Manager)**."
                )

    # SkillUp hosting guard
    if _SKILLUP_HOST_RE.search(user_text):
        resp_lower = response.lower()
        if not any(w in resp_lower for w in ("never", "must not", "do not", "don't", "cannot", "not used")):
            response = (
                "**Important:** **HackerRank SkillUp** (`hackerrank.com/skillup`) is strictly for "
                "self-paced student learning and certifications. It must **never** be used to host "
                "campus events, coding contests, or hackathons.\n\n"
                "To host your event, use **HackerRank for Work (HRW)** as the primary platform, "
                "or **HackerRank Community (HRC)** as a fallback if your HRW access is still pending."
            )

    chunks = chunk_message(response)

    t0 = state.get("_t0", 0.0)
    latency = (time.monotonic() - t0) * 1000 if t0 else 0.0
    if latency > 0:
        log.info("Pipeline latency: %.1fms (author=%s)", latency, state.get("author_name", "?"))

    return {"final_chunks": chunks, "latency_ms": latency}


# ---------------------------------------------------------------------------
# Conditional edge: sentinel verdict routing
# ---------------------------------------------------------------------------

def route_after_sentinel(state: PipelineState) -> str:
    if state.get("verdict") == "ENGAGE":
        return "knowledge"
    return END


# ---------------------------------------------------------------------------
# Graph assembly
# ---------------------------------------------------------------------------

def build_pipeline() -> StateGraph:
    graph = StateGraph(PipelineState)

    graph.add_node("sentinel", sentinel_node)
    graph.add_node("knowledge", knowledge_node)
    graph.add_node("replier", replier_node)
    graph.add_node("auditor", auditor_node)

    graph.set_entry_point("sentinel")
    graph.add_conditional_edges("sentinel", route_after_sentinel, {"knowledge": "knowledge", END: END})
    graph.add_edge("knowledge", "replier")
    graph.add_edge("replier", "auditor")
    graph.add_edge("auditor", END)

    return graph


_compiled_pipeline: CompiledStateGraph | None = None


def get_pipeline() -> CompiledStateGraph:
    global _compiled_pipeline
    if _compiled_pipeline is None:
        _compiled_pipeline = build_pipeline().compile()
    return _compiled_pipeline
