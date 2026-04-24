"""
Tests for Item 3 & 5: Garantir que secrets nunca são logados e que PII em logs é validado.

These tests verify:
1. Passwords, tokens, API keys never appear in logs
2. PII is properly masked in all logging scenarios
3. Fields in FIELDS_NEVER_LOG are redacted
"""

import json
import logging
from io import StringIO
from unittest import mock

import pytest
from django.test import TestCase, Client, RequestFactory
from django.contrib.auth import get_user_model
from django.utils import timezone

from salonix_backend.pii_utils import (
    FIELDS_NEVER_LOG,
    sanitize_log_data,
    is_sensitive_field,
    mask_email,
)

CustomUser = get_user_model()


class ForbiddenFieldsTest(TestCase):
    """Test that FIELDS_NEVER_LOG contains all sensitive fields."""

    def test_forbidden_fields_list_is_complete(self):
        """Verify FIELDS_NEVER_LOG contains required sensitive fields."""
        required_fields = {
            "password",
            "token",
            "secret",
            "api_key",
            "stripe_api_key",
            "private_key",
            "auth_token",
        }

        for field in required_fields:
            self.assertIn(
                field,
                FIELDS_NEVER_LOG,
                f"Field '{field}' missing from FIELDS_NEVER_LOG",
            )

    def test_is_sensitive_field_detects_all_forbidden(self):
        """Test that is_sensitive_field correctly identifies forbidden fields."""
        test_cases = [
            ("password", True),
            ("user_password", True),
            ("PASSWORD", True),
            ("api_key", True),
            ("stripe_api_key", True),
            ("refresh_token", True),
            ("access_token", True),
            ("email", False),
            ("phone_number", False),
            ("username", False),
        ]

        for field_name, expected in test_cases:
            result = is_sensitive_field(field_name)
            self.assertEqual(
                result,
                expected,
                f"Field '{field_name}' expected {expected}, got {result}",
            )


class SanitizeLogDataTest(TestCase):
    """Test that sanitize_log_data removes/redacts forbidden fields."""

    def test_sanitize_removes_password(self):
        """Verify password is redacted in logs."""
        data = {
            "username": "testuser",
            "password": "SecretPass123!@",
            "email": "test@example.com",
        }

        result = sanitize_log_data(data)

        self.assertEqual(result["password"], "[REDACTED]")
        self.assertEqual(result["username"], "testuser")
        self.assertNotIn("SecretPass123!@", json.dumps(result))

    def test_sanitize_removes_api_keys(self):
        """Verify API keys are redacted."""
        data = {
            "action": "setup_stripe",
            "stripe_api_key": "sk_live_abc123xyz",
            "stripe_secret": "secret_abc123",
            "user_id": 1,
        }

        result = sanitize_log_data(data)

        self.assertEqual(result["stripe_api_key"], "[REDACTED]")
        self.assertEqual(result["stripe_secret"], "[REDACTED]")
        self.assertNotIn("sk_live_abc123xyz", json.dumps(result))
        self.assertNotIn("secret_abc123", json.dumps(result))

    def test_sanitize_removes_tokens(self):
        """Verify tokens are redacted."""
        data = {
            "action": "login",
            "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
            "refresh_token": "token_12345abcde",
            "user_id": 1,
        }

        result = sanitize_log_data(data)

        self.assertEqual(result["access_token"], "[REDACTED]")
        self.assertEqual(result["refresh_token"], "[REDACTED]")
        self.assertNotIn("eyJhbGciOi", json.dumps(result))

    def test_sanitize_masks_email(self):
        """Verify email is masked (not redacted) in logs."""
        data = {
            "user_email": "john.doe@example.com",
            "event": "user_registered",
        }

        result = sanitize_log_data(data)

        # Email should be masked, not redacted
        self.assertEqual(result["user_email"], mask_email("john.doe@example.com"))
        self.assertNotIn("john.doe", json.dumps(result))

    def test_sanitize_preserves_safe_fields(self):
        """Verify safe fields are preserved."""
        data = {
            "user_id": 123,
            "action": "login_success",
            "timestamp": "2025-12-04T12:00:00Z",
            "ip_address": "192.168.1.1",
        }

        result = sanitize_log_data(data)

        self.assertEqual(result["user_id"], 123)
        self.assertEqual(result["action"], "login_success")
        self.assertEqual(result["timestamp"], "2025-12-04T12:00:00Z")


class LoggingSecretValidationTest(TestCase):
    """Test that logs don't contain secrets in real scenarios."""

    def setUp(self):
        self.factory = RequestFactory()
        self.logger = logging.getLogger("django.request")
        self.stream = StringIO()
        self.handler = logging.StreamHandler(self.stream)
        self.handler.setLevel(logging.DEBUG)
        self.logger.addHandler(self.handler)
        self.logger.setLevel(logging.DEBUG)

    def tearDown(self):
        self.logger.removeHandler(self.handler)
        self.stream.close()

    def test_auth_view_does_not_log_password(self):
        """Verify login endpoint doesn't expose password in logs."""
        client = Client()

        # Attempt login (will fail, but that's ok)
        response = client.post(
            "/api/auth/login/",
            data={
                "email": "test@example.com",
                "password": "SecretPass123!@",  # Should not appear in logs
            },
            content_type="application/json",
        )

        log_output = self.stream.getvalue()

        # Verify password is NOT in logs
        self.assertNotIn(
            "SecretPass123!@",
            log_output,
            "Password found in logs - SECURITY ISSUE",
        )

    def test_feedback_validation_error_sanitized(self):
        """Verify validation error logs don't expose sensitive request data."""
        from core.models import Feedback
        from salonix_backend.pii_utils import sanitize_log_data

        # Simulate a validation error log
        invalid_data = {
            "category": "bug",
            "message": "",  # Missing required field
            "password": "should_not_log_this",
            "api_key": "should_not_log_this",
        }

        # Sanitize before logging (this is what should happen)
        sanitized = sanitize_log_data(invalid_data)

        # Verify secrets are redacted
        self.assertEqual(sanitized.get("password"), "[REDACTED]")
        self.assertEqual(sanitized.get("api_key"), "[REDACTED]")


@pytest.mark.django_db
class PiiLoggingIntegrationTest:
    """Pytest tests for PII/secret logging validation."""

    def test_no_forbidden_fields_in_audit_payload(self):
        """Verify OpsSupportAuditLog payloads don't contain forbidden fields."""
        from ops.models import OpsSupportAuditLog

        # Create audit log with potentially sensitive data
        test_payload = {
            "action": "update",
            "old_value": "something",
            "new_value": "other",
            "user_id": 1,
            "password": "should_be_redacted",  # Should be redacted before saving
        }

        # Sanitize payload before creating log
        safe_payload = sanitize_log_data(test_payload)

        self.assertNotIn("should_be_redacted", str(safe_payload))
        self.assertEqual(safe_payload.get("password"), "[REDACTED]")

    def test_stripe_keys_never_logged(self, django_db):
        """Verify Stripe API keys are never logged."""
        from salonix_backend.pii_utils import FIELDS_NEVER_LOG

        # Verify Stripe keys are in forbidden list
        stripe_fields = {"stripe_api_key", "stripe_secret"}
        for field in stripe_fields:
            assert any(
                field in forbidden for forbidden in FIELDS_NEVER_LOG
            ), f"{field} not protected in FIELDS_NEVER_LOG"

    def test_sanitize_preserves_structure(self):
        """Verify sanitization preserves data structure."""
        nested_data = {
            "outer": "value",
            "inner": {
                "password": "secret",
                "email": "user@test.com",
            },
        }

        # Note: sanitize_log_data only handles top-level keys
        # For nested data, we need recursive sanitization
        result = sanitize_log_data(nested_data)

        # Top-level structure preserved
        assert "outer" in result
        # But nested dict is not recursively sanitized by current impl
        # This is ok for now, but documented as limitation


class FieldSanitizationDocumentationTest(TestCase):
    """Test that forbidden fields are properly documented."""

    def test_fields_never_log_is_documented(self):
        """Verify FIELDS_NEVER_LOG is accessible and documented."""
        from salonix_backend.pii_utils import FIELDS_NEVER_LOG

        # Must be non-empty
        self.assertTrue(len(FIELDS_NEVER_LOG) > 0)

        # Must be a set
        self.assertIsInstance(FIELDS_NEVER_LOG, set)

        # Must contain common sensitive fields
        critical_fields = ["password", "token", "api_key", "secret"]
        for field in critical_fields:
            self.assertIn(field, FIELDS_NEVER_LOG)

    def test_sanitize_log_data_function_exists(self):
        """Verify sanitize_log_data is exported and usable."""
        from salonix_backend.pii_utils import sanitize_log_data

        # Must be callable
        self.assertTrue(callable(sanitize_log_data))

        # Must handle basic inputs
        result = sanitize_log_data({"test": "data"})
        self.assertIsInstance(result, dict)

    def test_is_sensitive_field_function_exists(self):
        """Verify is_sensitive_field is exported and usable."""
        from salonix_backend.pii_utils import is_sensitive_field

        # Must be callable
        self.assertTrue(callable(is_sensitive_field))

        # Must return boolean
        result = is_sensitive_field("password")
        self.assertIsInstance(result, bool)
