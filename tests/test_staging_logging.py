import pytest
from rest_framework.test import APIClient
from django.urls import reverse
from unittest.mock import patch, MagicMock
from users.models import CustomUser, Tenant, TenantStaffMember
import logging


@pytest.mark.django_db
class TestStagingLogging:
    def setup_method(self):
        self.client = APIClient()
        self.user = CustomUser.objects.create_user(
            username="testuser",
            email="test@example.com",
            password="password123",
            first_name="Test",
            last_name="User",
        )
        # Enable propagation
        self._old_propagate_users = logging.getLogger("users").propagate
        self._old_propagate_core = logging.getLogger("core").propagate
        logging.getLogger("users").propagate = True
        logging.getLogger("core").propagate = True

    def teardown_method(self):
        logging.getLogger("users").propagate = self._old_propagate_users
        logging.getLogger("core").propagate = self._old_propagate_core

    @patch("django.core.mail.EmailMultiAlternatives.send")
    def test_password_reset_email_failure_logs_error(self, mock_send, caplog):
        """Test that password reset email failure logs an error."""
        # Force send to fail
        mock_send.side_effect = Exception("SMTP Error")

        url = reverse("password_reset")
        with caplog.at_level(logging.ERROR):
            response = self.client.post(url, {"email": "test@example.com"})

        assert response.status_code == 200
        # Check logs
        assert "Falha ao enviar email de reset" in caplog.text
        # Check extra fields in records
        found = False
        for record in caplog.records:
            if "Falha ao enviar email de reset" in record.message:
                assert getattr(record, "error", "") == "SMTP Error"
                found = True
                break
        assert found

    @patch("core.views.FeedbackSerializer.save")
    def test_feedback_creation_unexpected_error_logs_exception(self, mock_save, caplog):
        """Test that unexpected error during feedback creation logs an exception."""
        # Authenticate user
        self.client.force_authenticate(user=self.user)

        # Setup tenant and role
        tenant = Tenant.objects.create(name="Test Tenant", slug="test-tenant")
        self.user.tenant = tenant
        self.user.save()
        TenantStaffMember.objects.create(
            user=self.user, tenant=tenant, role=TenantStaffMember.Role.OWNER
        )

        # Force save to fail
        mock_save.side_effect = Exception("Database Error")

        url = reverse("feedback-list-create")

        data = {
            "category": "app",
            "rating": 5,
            "message": "Test feedback",
            "captcha_token": "dev-bypass",
        }

        # We need to expect exception raised because we re-raise it in the view
        # after logging.
        with caplog.at_level(logging.ERROR):
            response = self.client.post(url, data)

        assert response.status_code == 500
        assert "feedback_create_failed_unexpected" in caplog.text
