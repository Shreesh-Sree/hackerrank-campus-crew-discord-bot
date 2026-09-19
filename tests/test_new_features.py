from __future__ import annotations

import os
from pathlib import Path

import pytest

os.environ.setdefault("DISCORD_BOT_TOKEN", "test-token")

from src.csv_validator import build_summary_embed, parse_contest_csv
from src.db import (
    _fetchall,
    award_points,
    check_and_grant_achievements,
    close_db,
    create_collab_request,
    create_ticket,
    get_ambassador_achievements,
    get_ambassador_events,
    get_ambassador_points,
    get_ambassador_profile,
    grant_achievement,
    init_db,
    record_event_submission,
    update_collab_status,
    update_ticket_status,
    upsert_ambassador_profile,
)
from src.prompts.template_manager import get_template_manager
from src.vision import is_image_attachment


@pytest.fixture(autouse=True)
def _use_temp_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import src.db as db_mod

    test_db = tmp_path / "test.db"
    monkeypatch.setattr(db_mod, "_SQLITE_PATH", test_db)
    monkeypatch.setattr(db_mod, "_using_postgres", False)
    db_mod._local.sqlite_conn = None  # type: ignore[attr-defined]
    init_db()
    yield
    close_db()


class TestVisionModule:
    def test_image_detection(self) -> None:
        assert is_image_attachment("error.png")
        assert is_image_attachment("screenshot.jpg")
        assert is_image_attachment("photo.JPEG")
        assert is_image_attachment("anim.gif")
        assert is_image_attachment("modern.webp")
        assert not is_image_attachment("data.csv")
        assert not is_image_attachment("report.pdf")
        assert not is_image_attachment("archive.zip")

    def test_vision_template_exists(self) -> None:
        tm = get_template_manager()
        result = tm.render_template("vision_analyzer")
        assert "screenshot" in result.lower()
        assert "Chakra" in result
        assert "Platform Identification" in result

    def test_event_wizard_template_exists(self) -> None:
        result = get_template_manager().render_template(
            "event_wizard",
            event_name="CodeStorm",
            event_format="contest",
            event_date="15 Nov 2026",
            platform="HRW",
            college_name="MIT",
            expected_participants="200",
        )
        assert "CodeStorm" in result
        assert "Promotion Timeline" in result
        assert "HRW" in result


class TestSmartAnalytics:
    def _make_csv(self, rows: list[list[str]]) -> bytes:
        return "\n".join(",".join(r) for r in rows).encode()

    def test_analytics_in_embed(self) -> None:
        csv = self._make_csv([
            ["Name", "Score"],
            ["Alice", "300"],
            ["Bob", "200"],
            ["Charlie", "50"],
            ["Zero", "0"],
        ])
        result = parse_contest_csv(csv, event_name="Test")
        embed = build_summary_embed(result)
        field_names = [f.name for f in embed.fields]
        assert "Analytics" in field_names

    def test_analytics_shows_completion_rate(self) -> None:
        csv = self._make_csv([
            ["Name", "Score"],
            ["A", "100"],
            ["B", "0"],
        ])
        result = parse_contest_csv(csv, event_name="Test")
        embed = build_summary_embed(result)
        analytics_field = [f for f in embed.fields if f.name == "Analytics"]
        assert len(analytics_field) == 1
        assert "Completion Rate" in analytics_field[0].value


class TestFiveMonthStreak:
    def test_streak_detection(self) -> None:
        for month in range(1, 6):
            record_event_submission(
                ambassador_id=50, ambassador_name="Streaker",
                event_name=f"Event M{month}", participant_count=100,
            )
            # Manually backdate the created_at for testing
            from src.db import _execute
            _execute(
                "UPDATE ambassador_events SET created_at=? WHERE event_name=?",
                (f"2026-{month:02d}-15T10:00:00+00:00", f"Event M{month}"),
            )
        award_points(ambassador_id=50, ambassador_name="Streaker",
                      points_delta=500, action_type="CONTEST_HOSTED")
        granted = check_and_grant_achievements(50)
        assert "five_streak" in granted

    def test_no_streak_with_gap(self) -> None:
        for month in [1, 2, 4, 5]:  # gap at month 3
            record_event_submission(
                ambassador_id=51, ambassador_name="Gapper",
                event_name=f"Event M{month}", participant_count=100,
            )
            from src.db import _execute
            _execute(
                "UPDATE ambassador_events SET created_at=? WHERE event_name=?",
                (f"2026-{month:02d}-15T10:00:00+00:00", f"Event M{month}"),
            )
        award_points(ambassador_id=51, ambassador_name="Gapper",
                      points_delta=400, action_type="CONTEST_HOSTED")
        granted = check_and_grant_achievements(51)
        assert "five_streak" not in granted


class TestCollaboratorAchievement:
    def test_granted_on_completed_collab(self) -> None:
        upsert_ambassador_profile(ambassador_id=60, ambassador_name="CollabUser")
        award_points(ambassador_id=60, ambassador_name="CollabUser",
                      points_delta=100, action_type="CONTEST_HOSTED")
        record_event_submission(
            ambassador_id=60, ambassador_name="CollabUser",
            event_name="Joint Event", participant_count=200,
        )
        req = create_collab_request(
            requester_id=60, requester_name="CollabUser",
            event_name="Joint Hack", target_country="India",
        )
        update_collab_status(req["id"], "COMPLETED")
        granted = check_and_grant_achievements(60)
        assert "collaborator" in granted

    def test_not_granted_on_open_collab(self) -> None:
        upsert_ambassador_profile(ambassador_id=61, ambassador_name="OpenCollab")
        award_points(ambassador_id=61, ambassador_name="OpenCollab",
                      points_delta=100, action_type="CONTEST_HOSTED")
        record_event_submission(
            ambassador_id=61, ambassador_name="OpenCollab",
            event_name="Solo Event", participant_count=100,
        )
        create_collab_request(
            requester_id=61, requester_name="OpenCollab",
            event_name="Open Collab", target_country="any",
        )
        granted = check_and_grant_achievements(61)
        assert "collaborator" not in granted


class TestP0FirstResponder:
    def test_granted_when_poc_acks_p0(self) -> None:
        upsert_ambassador_profile(ambassador_id=70, ambassador_name="Responder")
        award_points(ambassador_id=70, ambassador_name="Responder",
                      points_delta=100, action_type="CONTEST_HOSTED")
        record_event_submission(
            ambassador_id=70, ambassador_name="Responder",
            event_name="Event", participant_count=100,
        )
        ticket = create_ticket(
            channel_id=1, message_id=1, author_id=99, author_name="Reporter",
            category="TECH", urgency="P0", poc_name="sreesanth",
            poc_id="70",
        )
        update_ticket_status(ticket["ticket_code"], "ACKNOWLEDGED")
        granted = check_and_grant_achievements(70)
        assert "first_responder" in granted


class TestQuizQuestions:
    def test_quiz_has_5_questions(self) -> None:
        from src.slash_commands import QUIZ_QUESTIONS
        assert len(QUIZ_QUESTIONS) == 5
        for q in QUIZ_QUESTIONS:
            assert "q" in q
            assert "options" in q
            assert "answer" in q
            assert 0 <= q["answer"] < len(q["options"])

    def test_quiz_answers_correct(self) -> None:
        from src.slash_commands import QUIZ_QUESTIONS
        assert QUIZ_QUESTIONS[0]["options"][QUIZ_QUESTIONS[0]["answer"]] == "Chakra"
        assert QUIZ_QUESTIONS[1]["options"][QUIZ_QUESTIONS[1]["answer"]] == "No, never"
        assert QUIZ_QUESTIONS[2]["options"][QUIZ_QUESTIONS[2]["answer"]] == "300 participants"
        assert QUIZ_QUESTIONS[3]["options"][QUIZ_QUESTIONS[3]["answer"]] == "Submitted code/answers"
        assert QUIZ_QUESTIONS[4]["options"][QUIZ_QUESTIONS[4]["answer"]] == "No, never"
