from __future__ import annotations

import logging
from typing import Any, TypedDict

from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph import END, StateGraph

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


class PipelineState(TypedDict, total=False):
    message_content: str
    author_name: str
    author_id: int
    channel_id: int
    is_dm: bool
    is_mention: bool
    is_bot: bool

    verdict: str
    knowledge_context: str
    raw_response: str
    final_chunks: list[str]
    escalation_target: str | None
    error: str | None


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
    if state.get("is_bot"):
        return {"verdict": "DISMISS"}

    if state.get("is_dm") or state.get("is_mention"):
        return {"verdict": "ENGAGE"}

    text = state["message_content"].strip()

    if is_noise(text):
        log.debug("Sentinel: noise gate caught '%s'", text[:60])
        return {"verdict": "DISMISS"}

    if has_campus_crew_intent(text):
        return {"verdict": "ENGAGE"}

    try:
        classifier = get_classifier_llm()
        result = await classifier.ainvoke([
            SystemMessage(content=CLASSIFIER_SYSTEM_PROMPT),
            HumanMessage(content=text),
        ])
        decision = result.content.strip().upper()
        if "REPLY" in decision and "NO_REPLY" not in decision:
            return {"verdict": "ENGAGE"}
        return {"verdict": "DISMISS"}
    except Exception:
        log.exception("Sentinel LLM classification failed, defaulting to DISMISS")
        return {"verdict": "DISMISS"}


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
        suffix = (
            f"\n\nNote: Based on the ambassador's query, this may need escalation to "
            f"the appropriate lead ({escalation.title()}). Include escalation guidance in your response."
        )
        system_prompt += suffix

    try:
        llm = get_llm()
        result = await llm.ainvoke([
            SystemMessage(content=system_prompt),
            HumanMessage(content=text),
        ])
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

    response = scrub_secrets(response)

    if contains_chakra_reference(state["message_content"]):
        chakra_check = response.lower()
        if "access" in chakra_check and "chakra" in chakra_check:
            if "never" not in chakra_check and "must not" not in chakra_check and "do not" not in chakra_check:
                response = (
                    "**Important:** The **Chakra** tab in HackerRank for Work is strictly internal "
                    "to HackerRank staff. As an ambassador, you must **never** access or click on it.\n\n"
                    "If you need mock interview features, please request mock interview vouchers "
                    "from **Sanskruti (Program Manager)**."
                )

    chunks = chunk_message(response)

    return {"final_chunks": chunks}


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


_compiled_pipeline = None


def get_pipeline():
    global _compiled_pipeline
    if _compiled_pipeline is None:
        _compiled_pipeline = build_pipeline().compile()
    return _compiled_pipeline
