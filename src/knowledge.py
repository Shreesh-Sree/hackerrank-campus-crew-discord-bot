from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

import yaml

log = logging.getLogger("hrcc.knowledge")

_ROOT = Path(__file__).resolve().parent.parent
_KNOWLEDGE_FILE = _ROOT / "knowledge_data.yaml"
_REFERENCES_DIR = _ROOT / "references"

_knowledge: dict[str, Any] | None = None
_reference_docs: dict[str, str] = {}
_reference_chunks: list[tuple[str, str]] = []

_CHUNK_SIZE = 600
_CHUNK_OVERLAP = 80


def load_knowledge() -> dict[str, Any]:
    global _knowledge
    if _knowledge is not None:
        return _knowledge

    if not _KNOWLEDGE_FILE.exists():
        log.error("knowledge_data.yaml not found at %s", _KNOWLEDGE_FILE)
        _knowledge = {}
        return _knowledge

    with open(_KNOWLEDGE_FILE, encoding="utf-8") as f:
        _knowledge = yaml.safe_load(f) or {}

    log.info("Loaded knowledge tree with %d top-level keys", len(_knowledge))
    return _knowledge


def load_references() -> dict[str, str]:
    global _reference_docs, _reference_chunks
    if _reference_docs:
        return _reference_docs

    if not _REFERENCES_DIR.is_dir():
        log.warning("references/ directory not found at %s", _REFERENCES_DIR)
        return _reference_docs

    for md_file in sorted(_REFERENCES_DIR.glob("*.md")):
        content = md_file.read_text(encoding="utf-8")
        _reference_docs[md_file.stem] = content
        log.info("Loaded reference doc: %s (%d chars)", md_file.stem, len(content))

    _reference_chunks = _chunk_all_references()
    log.info("Indexed %d reference chunks for RAG retrieval", len(_reference_chunks))
    return _reference_docs


def _chunk_all_references() -> list[tuple[str, str]]:
    chunks: list[tuple[str, str]] = []
    for doc_name, content in _reference_docs.items():
        sections = re.split(r"\n#{1,3}\s+", content)
        for section in sections:
            section = section.strip()
            if not section or len(section) < 30:
                continue

            if len(section) <= _CHUNK_SIZE:
                chunks.append((doc_name, section))
            else:
                words = section.split()
                start = 0
                while start < len(words):
                    end = start + _CHUNK_SIZE // 4
                    chunk_text = " ".join(words[start:end])
                    if chunk_text.strip():
                        chunks.append((doc_name, chunk_text))
                    start = end - (_CHUNK_OVERLAP // 4)
    return chunks


def retrieve_relevant_chunks(query: str, top_k: int = 5) -> list[str]:
    if not _reference_chunks:
        load_references()

    query_tokens = set(re.findall(r"\b\w{3,}\b", query.lower()))
    if not query_tokens:
        return []

    scored: list[tuple[float, str, str]] = []
    for doc_name, chunk_text in _reference_chunks:
        chunk_lower = chunk_text.lower()
        chunk_tokens = set(re.findall(r"\b\w{3,}\b", chunk_lower))

        overlap = query_tokens & chunk_tokens
        if not overlap:
            continue

        score = len(overlap)
        for token in overlap:
            score += chunk_lower.count(token) * 0.3

        scored.append((score, doc_name, chunk_text))

    scored.sort(key=lambda x: -x[0])

    results: list[str] = []
    seen_prefixes: set[str] = set()
    for _score, doc_name, chunk_text in scored[:top_k * 2]:
        prefix = chunk_text[:100]
        if prefix in seen_prefixes:
            continue
        seen_prefixes.add(prefix)
        results.append(f"[{doc_name}] {chunk_text}")
        if len(results) >= top_k:
            break

    return results


def get_platform_info(platform_key: str) -> dict[str, Any]:
    kb = load_knowledge()
    platforms = kb.get("platforms", {})
    return platforms.get(platform_key, {})


def get_reward_tier(participant_count: int) -> dict[str, Any]:
    kb = load_knowledge()
    tiers = kb.get("rewards", {}).get("tiers", {})
    if participant_count >= 300:
        return tiers.get("tier_300_plus", {})
    return tiers.get("under_300", {})


def get_escalation_info(lead_key: str) -> dict[str, Any]:
    kb = load_knowledge()
    return kb.get("escalations", {}).get(lead_key, {})


def get_certificate_info() -> dict[str, Any]:
    kb = load_knowledge()
    return kb.get("certificates", {})


def build_context_block(query: str = "") -> str:
    kb = load_knowledge()
    sections: list[str] = []

    for key in ("hrw", "hrc", "skillup"):
        plat = kb.get("platforms", {}).get(key, {})
        if plat:
            sections.append(
                f"## {plat.get('name', key.upper())}\n"
                f"URL: {plat.get('url', 'N/A')}\n"
                f"Use: {plat.get('primary_use', 'N/A')}\n"
            )
            if key == "hrw" and "security_warning" in plat:
                sw = plat["security_warning"]
                sections.append(
                    f"**SECURITY WARNING — {sw['tab_name']}:** {sw['policy']}\n"
                )
            rules = plat.get("rules", {})
            if isinstance(rules, dict):
                for rk, rv in rules.items():
                    sections.append(f"- {rk}: {rv}")
            elif isinstance(rules, str):
                sections.append(f"- {rules}")

    rewards = kb.get("rewards", {})
    if rewards:
        sections.append("\n## Reward Tiers")
        sections.append(f"Active Participant Definition: {rewards.get('participant_definition', {}).get('rule', 'N/A')}")
        for tier_key, tier_data in rewards.get("tiers", {}).items():
            sections.append(f"\n### {tier_data.get('threshold', tier_key)}")
            for pkg in tier_data.get("winner_package", []):
                sections.append(f"  - {pkg}")
            sections.append(f"  Merchandise: {'Yes' if tier_data.get('merchandise_included') else 'No'}")

    certs = kb.get("certificates", {})
    if certs:
        sections.append("\n## Certificates")
        sections.append(f"Eligibility: {certs.get('eligibility', 'N/A')}")
        sections.append(f"Template Lead: {certs.get('template_lead', 'N/A')}")
        schema = certs.get("canva_bulk_schema", {})
        if schema.get("headers"):
            sections.append(f"CSV Headers: {', '.join(schema['headers'])}")

    escalations = kb.get("escalations", {})
    if escalations:
        sections.append("\n## Escalation Directory")
        for lead_key, lead_data in escalations.items():
            sections.append(
                f"\n### {lead_data.get('name', lead_key)} ({lead_data.get('role', 'N/A')})"
            )
            for resp in lead_data.get("responsibilities", []):
                sections.append(f"  - {resp}")

    if query:
        relevant = retrieve_relevant_chunks(query, top_k=4)
        if relevant:
            sections.append("\n## Relevant Handbook Excerpts")
            for chunk in relevant:
                sections.append(chunk)

    return "\n".join(sections)
