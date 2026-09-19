from __future__ import annotations

import os

import pytest

os.environ.setdefault("DISCORD_BOT_TOKEN", "test-token")

from src.prompts.template_manager import get_template_manager


class TestCuratorPromptRendering:
    AUDIENCES = [
        ("freshers_beginner", "Freshers / Beginners"),
        ("intermediate_dsa", "Intermediate DSA"),
        ("placement_final_year", "Placement-Ready Final Year"),
    ]
    DURATIONS = [
        ("60_mins", "60 Minutes"),
        ("90_mins", "90 Minutes"),
        ("120_mins", "120 Minutes"),
        ("180_mins", "180 Minutes"),
    ]
    FOCUSES = [
        ("dsa_algorithms", "DSA & Algorithms"),
        ("web_dev_frontend", "Web Development / Frontend"),
        ("python_sql", "Python & SQL"),
        ("fullstack_debugging", "Full-Stack Debugging"),
    ]

    def test_all_audience_focus_combinations(self) -> None:
        tm = get_template_manager()
        for _, aud_label in self.AUDIENCES:
            for _, focus_label in self.FOCUSES:
                result = tm.render_template(
                    "contest_curator",
                    audience_label=aud_label,
                    duration_label="90 Minutes",
                    focus_label=focus_label,
                    college_name="",
                )
                assert "Question Distribution" in result
                assert aud_label in result
                assert focus_label in result

    def test_all_durations(self) -> None:
        tm = get_template_manager()
        for _, dur_label in self.DURATIONS:
            result = tm.render_template(
                "contest_curator",
                audience_label="Intermediate DSA",
                duration_label=dur_label,
                focus_label="DSA & Algorithms",
                college_name="",
            )
            assert dur_label in result

    def test_college_name_included_when_provided(self) -> None:
        result = get_template_manager().render_template(
            "contest_curator",
            audience_label="Freshers",
            duration_label="60 Minutes",
            focus_label="Python & SQL",
            college_name="NIT Trichy",
        )
        assert "NIT Trichy" in result

    def test_college_name_excluded_when_empty(self) -> None:
        result = get_template_manager().render_template(
            "contest_curator",
            audience_label="Freshers",
            duration_label="60 Minutes",
            focus_label="Python & SQL",
            college_name="",
        )
        assert "Institution" not in result

    def test_contains_required_sections(self) -> None:
        result = get_template_manager().render_template(
            "contest_curator",
            audience_label="Placement-Ready",
            duration_label="120 Minutes",
            focus_label="Full-Stack Debugging",
            college_name="",
        )
        required = [
            "Question Distribution",
            "Timing",
            "Scoring Rubric",
            "Anti-Cheating",
            "Candidate Instructions",
        ]
        for section in required:
            assert section in result, f"Missing section: {section}"

    def test_contains_buffer_time_warning(self) -> None:
        result = get_template_manager().render_template(
            "contest_curator",
            audience_label="Freshers",
            duration_label="60 Minutes",
            focus_label="DSA & Algorithms",
            college_name="",
        )
        assert "15-minute" in result or "15 minute" in result or "buffer" in result.lower()
