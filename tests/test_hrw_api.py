from __future__ import annotations

import asyncio
import os
import pytest

os.environ.setdefault("DISCORD_BOT_TOKEN", "test-token")


class TestHRWAPI:
    """Tests for HRW API integration."""

    def test_hrw_api_key_not_configured(self):
        """Test graceful handling when HRW API key is missing."""
        import src.config as config_mod
        original_key = config_mod.settings.hrw_api_key
        config_mod.settings.hrw_api_key = ""

        from src.hrw_api import get_questions_by_test

        questions = asyncio.run(get_questions_by_test("test-id"))
        assert questions == []

        config_mod.settings.hrw_api_key = original_key


class TestEmailVerification:
    """Tests for email verification module."""

    def test_validate_canva_csv_schema_valid(self):
        """Test validating a valid Canva CSV schema."""
        from src.verify_emails import validate_canva_csv_schema

        csv_content = (
            "Name,Email Address,College Name,Event Name,Date,Rank,Score\n"
            "Alice,alice@hrw.com,IIT Delhi,CodeStorm 2026,2026-09-15,1,300\n"
            "Bob,bob@hrw.com,IISc Bangalore,CodeStorm 2026,2026-09-15,2,280"
        )

        is_valid, warnings = validate_canva_csv_schema(csv_content, "Test Event")

        assert is_valid is True
        assert len(warnings) == 0

    def test_validate_canva_csv_schema_missing_columns(self):
        """Test validating CSV with missing required columns."""
        from src.verify_emails import validate_canva_csv_schema

        csv_content = "Name,Email\nAlice,alice@example.com"

        is_valid, warnings = validate_canva_csv_schema(csv_content, "Test Event")

        assert is_valid is False
        assert any("Missing" in w for w in warnings)

    def test_validate_canva_csv_schema_invalid_rank(self):
        """Test validating CSV with invalid rank values."""
        from src.verify_emails import validate_canva_csv_schema

        csv_content = (
            "Name,Email Address,College Name,Event Name,Date,Rank,Score\n"
            "Alice,alice@example.com,IIT Delhi,CodeStorm 2026,2026-09-15,-1,300\n"
            "Bob,bob@example.com,IISc Bangalore,CodeStorm 2026,2026-09-15,abc,280"
        )

        is_valid, warnings = validate_canva_csv_schema(csv_content, "Test Event")

        assert is_valid is False
        assert any("Invalid rank" in w for w in warnings)

    def test_validate_canva_csv_schema_empty_file(self):
        """Test validating empty CSV file."""
        from src.verify_emails import validate_canva_csv_schema

        csv_content = "Name,Email Address,College Name,Event Name,Date,Rank,Score"

        is_valid, warnings = validate_canva_csv_schema(csv_content, "Test Event")

        assert is_valid is False
        assert any("No participant" in w for w in warnings)

    def test_validate_canva_csv_schema_encoding_error(self):
        """Test validating CSV with encoding issues."""
        from src.verify_emails import validate_canva_csv_schema

        # Invalid UTF-8 bytes
        csv_content = b"\xff\xfeName,Email\n"

        is_valid, warnings = validate_canva_csv_schema(csv_content, "Test Event")

        assert is_valid is False
        assert any("UTF-8" in w for w in warnings)


class TestGenerateVerificationReport:
    """Tests for report generation."""

    def test_generate_verification_report_success(self):
        """Test generating a successful verification report."""
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

    def test_generate_verification_report_empty(self):
        """Test generating a report with no results."""
        from src.verify_emails import generate_verification_report

        report = generate_verification_report([])

        assert "Total checked: 0" in report


class TestRunFullVerification:
    """Tests for full verification pipeline."""

    def test_run_full_verification_success(self):
        """Test complete verification pipeline with valid data."""
        from src.verify_emails import run_full_verification
        import unittest.mock as mock

        csv_content = (
            "Name,Email Address,College Name,Event Name,Date,Rank,Score\n"
            "Alice,alice@hrw.com,IIT Delhi,CodeStorm 2026,2026-09-15,1,300"
        )

        # Mock HRW API to return a matching user
        with mock.patch("src.verify_emails.find_hrw_user_by_email") as mock_find:
            mock_find.return_value = {"user_id": "123", "email": "alice@hrw.com"}
            result = asyncio.run(run_full_verification(csv_content, "Test Event"))

            assert result["event_name"] == "Test Event"
            assert result["total_participants"] == 1
            assert result["valid_emails"] == 1
            assert result["invalid_emails"] == 0
            assert result["can_submit_to_sanskruti"] is True
            assert result["schema_valid"] is True

    def test_run_full_verification_with_mismatches(self):
        """Test verification pipeline with email mismatches."""
        from src.verify_emails import run_full_verification
        import unittest.mock as mock

        csv_content = (
            "Name,Email Address,College Name,Event Name,Date,Rank,Score\n"
            "Alice,alice@submitted.com,IIT Delhi,CodeStorm 2026,2026-09-15,1,300"
        )

        # Mock HRW API to return a different email for the user
        with mock.patch("src.verify_emails.find_hrw_user_by_email") as mock_find:
            mock_find.return_value = {"user_id": "123", "email": "alice@hrw.com"}
            result = asyncio.run(run_full_verification(csv_content, "Test Event"))

            assert result["total_participants"] == 1
            assert result["valid_emails"] == 0
            assert result["invalid_emails"] == 1
            assert result["can_submit_to_sanskruti"] is False
            assert len(result["warnings"]) > 0
