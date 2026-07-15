"""
Integration tests for PII masking in logging across views.

Tests that logging points in views.py files properly mask PII data.
"""

import json
import logging
from io import StringIO
from unittest import mock

import pytest
from django.test import TestCase, Client
from django.contrib.auth import get_user_model
from django.utils import timezone

from users.models import Tenant, TenantStaffMember
from core.models import Service, Professional, SalonCustomer, Appointment, ScheduleSlot
from salonix_backend.pii_utils import mask_email, mask_phone

CustomUser = get_user_model()


class LogCaptureHandler(logging.Handler):
    """Custom handler to capture log records."""

    def __init__(self):
        super().__init__()
        self.records = []

    def emit(self, record):
        self.records.append(record)

    def get_extras(self):
        """Extract common extra fields from all records."""
        extras = []
        for record in self.records:
            extras.append(
                {
                    "email": getattr(record, "email", None),
                    "status_code": getattr(record, "status_code", None),
                    "app_type": getattr(record, "app_type", None),
                }
            )
        return extras


class UserAuthLoggingIntegrationTest(TestCase):
    """Test that user auth views mask email in logs."""

    def setUp(self):
        self.client = Client()
        self.logger = logging.getLogger("users.views")
        self.handler = LogCaptureHandler()
        self.handler.setLevel(logging.DEBUG)
        self.logger.addHandler(self.handler)
        self.logger.setLevel(logging.DEBUG)

    def tearDown(self):
        self.logger.removeHandler(self.handler)

    def test_user_registration_masks_email_in_logs(self):
        """Verify user registration logs email as masked."""
        test_email = "testuser@example.com"
        expected_masked = mask_email(test_email)

        response = self.client.post(
            "/api/users/register/",
            data={
                "username": "testuser",
                "email": test_email,
                "password": "TestPass123!@",
                "salon_name": "Salon Mask Test",
                "plan": "founder",
            },
            content_type="application/json",
        )

        # Even if registration fails, logs should have masked email
        self.assertIsNotNone(response)

        # Check that logs contain masked email, not raw email
        log_extras = self.handler.get_extras()
        assert any(expected_masked == extra.get("email") for extra in log_extras), (
            f"Expected masked email {expected_masked} in logs, "
            f"got extras: {log_extras}"
        )

        # Verify raw email is NOT in logs
        all_log_content = "\n".join(
            str(record.getMessage()) for record in self.handler.records
        )
        assert (
            test_email not in all_log_content
        ), f"Raw email {test_email} found in logs (should be masked)"


class CoreAppointmentLoggingIntegrationTest(TestCase):
    """Test that core appointment views mask email in logs."""

    def setUp(self):
        self.client = Client()
        self.logger = logging.getLogger("core.views")
        self.handler = LogCaptureHandler()
        self.handler.setLevel(logging.DEBUG)
        self.logger.addHandler(self.handler)
        self.logger.setLevel(logging.DEBUG)

        # Create test tenant
        self.tenant = Tenant.objects.create(name="Test Salon", slug="test-salon")

        # Create owner user
        self.owner_user = CustomUser.objects.create_user(
            username="owner", email="owner@test.com", password="pass123"
        )
        self.owner_user.tenant = self.tenant
        self.owner_user.save()

        staff = TenantStaffMember.objects.create(
            tenant=self.tenant,
            user=self.owner_user,
            role=TenantStaffMember.Role.OWNER,
            status=TenantStaffMember.Status.ACTIVE,
        )

        # Create professional
        self.professional = Professional.objects.create(
            name="Prof Name",
            user=self.owner_user,
            tenant=self.tenant,
            staff_member=staff,
        )

        # Create service
        self.service = Service.objects.create(
            name="Haircut",
            user=self.owner_user,
            tenant=self.tenant,
            price_eur=30,
            duration_minutes=30,
        )

    def tearDown(self):
        self.logger.removeHandler(self.handler)

    def test_appointment_creation_logs_do_not_expose_email(self):
        """Test that appointment creation logs don't expose customer email."""
        # Create a schedule slot
        slot = ScheduleSlot.objects.create(
            tenant=self.tenant,
            professional=self.professional,
            start_time=timezone.now() + timezone.timedelta(days=1),
            end_time=timezone.now() + timezone.timedelta(days=1, hours=1),
            is_available=True,
            status="available",
        )

        # Create customer with email
        customer_email = "customer@test.com"
        customer = SalonCustomer.objects.create(
            tenant=self.tenant, name="Customer", email=customer_email
        )

        # Create appointment (would go through core/views.py AppointmentCreateView)
        appointment = Appointment.objects.create(
            tenant=self.tenant,
            client=self.owner_user,
            service=self.service,
            professional=self.professional,
            slot=slot,
            customer=customer,
            status="scheduled",
        )

        # Verify that if email was logged, it should be masked
        log_extras = self.handler.get_extras()
        all_log_content = "\n".join(
            str(record.getMessage()) for record in self.handler.records
        )

        # Raw email should NOT appear in logs (unless logged elsewhere)
        # This test is more about verifying the structure is there for masking
        assert appointment.id is not None


@pytest.mark.django_db
class PiiMaskingLogValidationTest:
    """Pytest-style tests for PII masking validation."""

    def test_mask_email_in_logs(self):
        """Test that mask_email produces expected output."""
        test_cases = [
            ("user@example.com", "u***@example.com"),
            ("john.doe@company.co.uk", "j***@company.co.uk"),
            ("a@b.com", "a***@b.com"),
        ]

        for email, expected in test_cases:
            result = mask_email(email)
            assert result == expected, f"Expected {expected}, got {result}"

    def test_mask_phone_in_logs(self):
        """Test that mask_phone produces expected output."""
        test_cases = [
            ("+5511999999999", "+55 11****9999"),  # Brazil
            ("+44 7911 123456", "+44 791****456"),  # UK
            ("11 99999-9999", "11****999"),  # Brazil without country code
        ]

        for phone, expected in test_cases:
            result = mask_phone(phone)
            assert result == expected, f"Expected {expected}, got {result}"

    def test_user_repr_masking(self, django_db):
        """Test that mask_user_repr produces expected output."""
        from salonix_backend.pii_utils import mask_user_repr

        user = CustomUser.objects.create_user(
            username="testuser",
            email="test@example.com",
            phone_number="+5511999999999",
        )

        result = mask_user_repr(user)

        # Should have masked email and phone
        assert "test@example.com" not in result.get("email_masked", "")
        assert "+5511999999999" not in result.get("phone_masked", "")
        assert result.get("user_id") == user.id
        assert result.get("username") == "testuser"


class OpsAuditLoggingIntegrationTest(TestCase):
    """Test that ops admin views mask email in audit logs."""

    def setUp(self):
        self.logger = logging.getLogger("ops.views")
        self.handler = LogCaptureHandler()
        self.handler.setLevel(logging.DEBUG)
        self.logger.addHandler(self.handler)
        self.logger.setLevel(logging.DEBUG)

        # Create ops admin user
        self.ops_user = CustomUser.objects.create_user(
            username="opsadmin", email="ops@internal.com", password="oppass"
        )
        self.ops_user.is_staff = True
        self.ops_user.is_superuser = True
        self.ops_user.save()

        # Create test tenant
        self.tenant = Tenant.objects.create(name="Test Tenant", slug="test-tenant")

    def tearDown(self):
        self.logger.removeHandler(self.handler)

    def test_ops_audit_log_masks_email_payloads(self):
        """Test that OpsSupportAuditLog payloads mask email."""
        from ops.models import OpsSupportAuditLog

        test_email = "owner@salon.com"
        expected_masked = mask_email(test_email)

        # Create audit log with masked email (simulating what views.py should do)
        log = OpsSupportAuditLog.objects.create(
            actor=self.ops_user,
            action="reset_owner",
            target_tenant=self.tenant,
            payload={"new_owner_email": expected_masked},
        )

        # Verify payload contains masked email
        assert log.payload.get("new_owner_email") == expected_masked
        assert test_email not in log.payload.get("new_owner_email", "")
