from __future__ import annotations

import os

import pytest

os.environ.setdefault("DISCORD_BOT_TOKEN", "test-token")

from src.prompts.template_manager import TemplateManager, get_template_manager


EXPECTED_TEMPLATES = [
    "contest_curator.jinja",
    "marketing_copy.jinja",
    "replier.jinja",
    "sentinel_classifier.jinja",
    "system_message.jinja",
]


class TestTemplateManager:
    def test_singleton(self) -> None:
        tm1 = get_template_manager()
        tm2 = get_template_manager()
        assert tm1 is tm2

    def test_all_templates_exist(self) -> None:
        tm = get_template_manager()
        available = tm.list_templates()
        for name in EXPECTED_TEMPLATES:
            assert name in available, f"Missing template: {name}"

    def test_list_templates(self) -> None:
        tm = get_template_manager()
        templates = tm.list_templates()
        assert len(templates) >= 5


class TestSystemMessageTemplate:
    def test_renders_cleanly(self) -> None:
        tm = get_template_manager()
        result = tm.render_template("system_message")
        assert "HackerRank Campus Crew" in result
        assert "Chakra" in result
        assert "SkillUp" in result
        assert "Sanskruti" in result
        assert "Sreesanth" in result
        assert "Nitish" in result

    def test_contains_hard_rules(self) -> None:
        result = get_template_manager().render_template("system_message")
        assert "STRICTLY INTERNAL" in result
        assert "self-paced learning" in result
        assert "300 active participants" in result


class TestSentinelClassifierTemplate:
    def test_renders_cleanly(self) -> None:
        result = get_template_manager().render_template("sentinel_classifier")
        assert "REPLY" in result
        assert "NO_REPLY" in result
        assert "intent classifier" in result.lower()


class TestReplierTemplate:
    def test_renders_with_context(self) -> None:
        result = get_template_manager().render_template(
            "replier",
            knowledge_context="## Test Knowledge\nThis is test context.",
            escalation_target=None,
        )
        assert "Test Knowledge" in result
        assert "HackerRank Campus Crew" in result
        assert "tools" in result.lower()

    def test_renders_with_escalation(self) -> None:
        result = get_template_manager().render_template(
            "replier",
            knowledge_context="context here",
            escalation_target="sanskruti",
        )
        assert "Sanskruti" in result
        assert "escalation" in result.lower()

    def test_renders_without_escalation(self) -> None:
        result = get_template_manager().render_template(
            "replier",
            knowledge_context="context here",
            escalation_target=None,
        )
        assert "context here" in result


class TestContestCuratorTemplate:
    def test_renders_with_all_params(self) -> None:
        result = get_template_manager().render_template(
            "contest_curator",
            audience_label="Intermediate DSA",
            duration_label="90 Minutes",
            focus_label="DSA & Algorithms",
            college_name="IIT Madras",
        )
        assert "Intermediate DSA" in result
        assert "90 Minutes" in result
        assert "DSA & Algorithms" in result
        assert "IIT Madras" in result
        assert "Question Distribution" in result
        assert "Scoring Rubric" in result
        assert "Anti-Cheating" in result

    def test_renders_without_college(self) -> None:
        result = get_template_manager().render_template(
            "contest_curator",
            audience_label="Freshers",
            duration_label="60 Minutes",
            focus_label="Python & SQL",
            college_name="",
        )
        assert "Freshers" in result
        assert "Institution" not in result


class TestMarketingCopyTemplate:
    def test_renders_with_event_details(self) -> None:
        result = get_template_manager().render_template(
            "marketing_copy",
            event_name="CodeStorm 2026",
            date="19 September 2026",
            time="3:00 PM IST",
            url="https://hackerrank.com/contests/codestorm",
        )
        assert "CodeStorm 2026" in result
        assert "19 September 2026" in result
        assert "Discord" in result
        assert "WhatsApp" in result
        assert "LinkedIn" in result


class TestTemplateAutoExtension:
    def test_adds_jinja_extension(self) -> None:
        result = get_template_manager().render_template("system_message")
        assert len(result) > 100

    def test_explicit_extension_works(self) -> None:
        result = get_template_manager().render_template("system_message.jinja")
        assert len(result) > 100
