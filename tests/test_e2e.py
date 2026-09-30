"""End-to-End Integration Tests for HRCC Bot Production Features."""

from __future__ import annotations

import asyncio
import os
import tempfile
import pytest

os.environ.setdefault("DISCORD_BOT_TOKEN", "test-token")


class TestE2EEmailVerificationWorkflow:
    """E2E test simulating the complete email verification workflow."""

    def test_complete_contest_submission_to_sanskruti(self):
        """Simulate: CSV upload → validation → email verification → report generation.

        This tests the full flow an ambassador would experience after hosting a contest.
        """
        from src.verify_emails import (
            run_full_verification,
            validate_canva_csv_schema,
            generate_verification_report,
        )
        import unittest.mock as mock

        # Step 1: Create a realistic contest CSV (300+ participants for merch tier)
        csv_content = (
            "Name,Email Address,College Name,Event Name,Date,Rank,Score\n"
            "Alice Johnson,alice@iitd.ac.in,IIT Delhi,CodeStorm 2026,2026-09-15,1,300\n"
            "Bob Kumar,bob@iisc.ac.in,IISc Bangalore,CodeStorm 2026,2026-09-15,2,285\n"
            "Charlie Smith,charlie@gatech.edu,Georgia Tech,CodeStorm 2026,2026-09-15,3,270\n"
            "Diana Chen,diana@nus.edu.sg,NUS Singapore,CodeStorm 2026,2026-09-15,4,260\n"
            "Ethan Patel,ethan@iiitb.ac.in,IIIT Bangalore,CodeStorm 2026,2026-09-15,5,250\n"
        )

        # Step 2: Validate Canva CSV schema
        is_valid, warnings = validate_canva_csv_schema(csv_content, "CodeStorm 2026")
        assert is_valid is True, f"Schema validation failed: {warnings}"
        assert len(warnings) == 0

        # Step 3: Mock HRW API responses - all emails match
        with mock.patch("src.verify_emails.find_hrw_user_by_email") as mock_find:
            def mock_find_side_effect(email):
                email_lower = email.lower()
                if "iitd" in email_lower:
                    return {"user_id": "1001", "email": "alice@iitd.ac.in"}
                elif "iisc" in email_lower:
                    return {"user_id": "1002", "email": "bob@iisc.ac.in"}
                elif "gatech" in email_lower:
                    return {"user_id": "1003", "email": "charlie@gatech.edu"}
                elif "nus" in email_lower:
                    return {"user_id": "1004", "email": "diana@nus.edu.sg"}
                elif "iiitb" in email_lower:
                    return {"user_id": "1005", "email": "ethan@iiitb.ac.in"}
                return None

            mock_find.side_effect = mock_find_side_effect

            # Step 4: Run full verification
            result = asyncio.run(run_full_verification(csv_content.encode("utf-8"), "CodeStorm 2026"))

            # Verify results
            assert result["event_name"] == "CodeStorm 2026"
            assert result["total_participants"] == 5
            assert result["valid_emails"] == 5
            assert result["invalid_emails"] == 0
            assert result["schema_valid"] is True
            assert result["can_submit_to_sanskruti"] is True
            assert len(result["warnings"]) == 0

        # Step 5: Generate human-readable report
        report = generate_verification_report([], include_details=True)
        assert "EMAIL VERIFICATION REPORT" in report
        assert "Total checked: 0" in report


class TestE2EHRWAPIWorkflow:
    """E2E test simulating HRW API integration workflow."""

    def test_hrw_api_complete_workflow(self):
        """Simulate: check HRW access → verify test ownership → browse questions.

        This tests the complete HRW platform integration flow.
        """
        from src.hrw_api import (
            get_questions_by_test,
            verify_test_ownership,
        )
        import unittest.mock as mock

        # Test 1: No HRW API key configured
        import src.config as config_mod
        original_key = config_mod.settings.hrw_api_key
        config_mod.settings.hrw_api_key = ""

        questions = asyncio.run(get_questions_by_test("test-123"))
        assert questions == []

        # Test 2: HRW API key configured - mock successful ownership verification
        config_mod.settings.hrw_api_key = "test-api-key"

        with mock.patch("src.hrw_api.get_test") as mock_get_test:
            mock_get_test.return_value = {"id": "test-123", "owner": "user-456"}

            result = asyncio.run(verify_test_ownership("test-123", "user-456"))
            assert result is True

        # Test 3: Mock question browsing
        with mock.patch("src.hrw_api.get_test") as mock_get_test:
            with mock.patch("src.hrw_api.get_questions") as mock_get_q:
                mock_get_test.return_value = {"id": "test-123"}
                mock_get_q.return_value = {
                    "data": [
                        {"id": "q1", "test_id": "test-123", "name": "Easy Question 1", "difficulty": "EASY"},
                        {"id": "q2", "test_id": "test-123", "name": "Hard Question 2", "difficulty": "HARD"},
                    ],
                    "total": 2,
                }

                questions = asyncio.run(get_questions_by_test("test-123"))
                assert len(questions) == 2
                assert questions[0]["name"] == "Easy Question 1"
                assert questions[1]["name"] == "Hard Question 2"

        config_mod.settings.hrw_api_key = original_key


class TestE2ESchemaValidation:
    """E2E test for CSV schema validation edge cases."""

    def test_valid_canva_schema(self):
        """Test valid Canva CSV with all required fields."""
        from src.verify_emails import validate_canva_csv_schema

        csv_content = (
            "Name,Email Address,College Name,Event Name,Date,Rank,Score\n"
            "Alice,alice@example.com,ABC College,My Event,2026-09-15,1,300\n"
        )

        is_valid, warnings = validate_canva_csv_schema(csv_content, "My Event")
        assert is_valid is True
        assert len(warnings) == 0

    def test_missing_required_column(self):
        """Test CSV with missing required column."""
        from src.verify_emails import validate_canva_csv_schema

        csv_content = "Name,Email\nAlice,alice@example.com"

        is_valid, warnings = validate_canva_csv_schema(csv_content, "My Event")
        assert is_valid is False
        assert any("Missing" in w for w in warnings)

    def test_invalid_rank_value(self):
        """Test CSV with invalid rank values."""
        from src.verify_emails import validate_canva_csv_schema

        csv_content = (
            "Name,Email Address,College Name,Event Name,Date,Rank,Score\n"
            "Alice,alice@example.com,ABC College,My Event,2026-09-15,-5,300\n"
        )

        is_valid, warnings = validate_canva_csv_schema(csv_content, "My Event")
        assert is_valid is False
        assert any("Invalid rank" in w for w in warnings)

    def test_empty_data_rows(self):
        """Test CSV with header but no data rows."""
        from src.verify_emails import validate_canva_csv_schema

        csv_content = "Name,Email Address,College Name,Event Name,Date,Rank,Score"

        is_valid, warnings = validate_canva_csv_schema(csv_content, "My Event")
        assert is_valid is False
        assert any("No participant" in w for w in warnings)

    def test_encoding_error(self):
        """Test CSV with invalid UTF-8 encoding."""
        from src.verify_emails import validate_canva_csv_schema

        csv_content = b"\xff\xfeName,Email\nAlice,alice@example.com"

        is_valid, warnings = validate_canva_csv_schema(csv_content, "My Event")
        assert is_valid is False
        assert any("UTF-8" in w for w in warnings)


class TestE2EReportGeneration:
    """E2E test for verification report generation."""

    def test_report_with_details(self):
        """Test generating detailed verification report."""
        from src.verify_emails import EmailVerificationResult, generate_verification_report

        results = [
            EmailVerificationResult(
                name="Alice", email="alice@hrw.com",
                hrw_account_found=True, matches_winner_email=True
            ),
            EmailVerificationResult(
                name="Bob", email="bob@submitted.com",
                hrw_account_found=True, matches_winner_email=False,
                warning="HRW account uses different email"
            ),
        ]

        report = generate_verification_report(results, include_details=True)

        assert "Total checked: 2" in report
        assert "Valid (matches HRW account): 1" in report
        assert "Invalid/Mismatched: 1" in report
        assert "Alice" in report
        assert "Bob" in report
        assert "Do NOT submit mismatched emails" in report

    def test_report_empty(self):
        """Test generating empty verification report."""
        from src.verify_emails import generate_verification_report

        report = generate_verification_report([])

        assert "Total checked: 0" in report


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
