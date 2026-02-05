"""
Testes para novo fluxo de cancelamento de conta (BE-ACCOUNT-CANCEL #396).
"""

from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase
from users.models import Tenant, CustomUser, TenantStaffMember
from django.utils import timezone
from datetime import timedelta
from unittest.mock import patch, MagicMock


class TenantCancellationNewFlowTest(APITestCase):
    """
    Tests para o novo fluxo de cancelamento (BE-ACCOUNT-CANCEL #396).
    Cobre soft delete, Stripe, emails, e período de retenção.
    """

    def setUp(self):
        # Create Tenant
        self.tenant = Tenant.objects.create(
            name="Test Salon",
            slug="test-salon",
            plan_tier="standard",
            status=Tenant.STATUS_ACTIVE,
        )

        # Create Owner
        self.owner = CustomUser.objects.create_user(
            username="owner",
            email="owner@example.com",
            password="TestPassword123!",
            tenant=self.tenant,
        )
        self.staff_owner = TenantStaffMember.objects.create(
            tenant=self.tenant, user=self.owner, role=TenantStaffMember.Role.OWNER
        )

        # Create Manager
        self.manager = CustomUser.objects.create_user(
            username="manager",
            email="manager@example.com",
            password="password123",
            tenant=self.tenant,
        )
        self.staff_manager = TenantStaffMember.objects.create(
            tenant=self.tenant, user=self.manager, role=TenantStaffMember.Role.MANAGER
        )

        self.cancel_url = reverse("tenant-cancel")
        self.reactivate_url = reverse("tenant-reactivate")

    @patch("core.email_utils.send_account_cancellation_email")
    @patch("payments.services.SubscriptionService.cancel_tenant_subscriptions")
    def test_owner_can_cancel_account_with_confirmation(
        self, mock_stripe_cancel, mock_email
    ):
        """Testa cancelamento completo com validações."""
        mock_stripe_cancel.return_value = {"success": True, "cancelled_count": 1}
        mock_email.return_value = True

        self.client.force_authenticate(user=self.owner)
        response = self.client.post(
            self.cancel_url,
            {
                "password": "TestPassword123!",
                "confirmation_text": "CANCELAR CONTA",
                "cancellation_reason": "Not using anymore",
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("message", response.data)
        self.assertIn("cancelled_at", response.data)
        self.assertIn("deletion_date", response.data)
        self.assertIn("reactivation_link", response.data)

        # Verify tenant status
        self.tenant.refresh_from_db()
        self.assertEqual(self.tenant.status, Tenant.STATUS_CANCELLED)
        self.assertIsNotNone(self.tenant.cancelled_at)
        self.assertIsNotNone(self.tenant.scheduled_deletion_at)
        self.assertIsNotNone(self.tenant.reactivation_token)
        self.assertEqual(self.tenant.cancellation_reason, "Not using anymore")

        # Verify Stripe was called
        mock_stripe_cancel.assert_called_once_with(self.tenant)

        # Verify email was sent
        self.assertEqual(mock_email.call_count, 1)

    def test_cancel_requires_correct_password(self):
        """Testa que senha incorreta bloqueia cancelamento."""
        self.client.force_authenticate(user=self.owner)
        response = self.client.post(
            self.cancel_url,
            {
                "password": "WrongPassword",
                "confirmation_text": "CANCELAR CONTA",
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        # Verify error message contains password error
        self.assertIn("password", str(response.data).lower())

        # Verify tenant not cancelled
        self.tenant.refresh_from_db()
        self.assertEqual(self.tenant.status, Tenant.STATUS_ACTIVE)

    def test_cancel_requires_confirmation_text(self):
        """Testa que texto de confirmação é obrigatório."""
        self.client.force_authenticate(user=self.owner)
        response = self.client.post(
            self.cancel_url,
            {
                "password": "TestPassword123!",
                "confirmation_text": "wrong text",
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

        # Verify tenant not cancelled
        self.tenant.refresh_from_db()
        self.assertEqual(self.tenant.status, Tenant.STATUS_ACTIVE)

    def test_manager_cannot_cancel_account(self):
        """Testa que manager não pode cancelar."""
        self.client.force_authenticate(user=self.manager)
        response = self.client.post(
            self.cancel_url,
            {
                "password": "password123",
                "confirmation_text": "CANCELAR CONTA",
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

        # Verify tenant not cancelled
        self.tenant.refresh_from_db()
        self.assertEqual(self.tenant.status, Tenant.STATUS_ACTIVE)

    @patch("core.email_utils.send_account_reactivation_email")
    def test_owner_can_reactivate_within_retention_period(self, mock_email):
        """Testa reativação dentro do período de retenção."""
        mock_email.return_value = True

        # Setup cancelled tenant
        self.tenant.status = Tenant.STATUS_CANCELLED
        self.tenant.cancelled_at = timezone.now()
        self.tenant.scheduled_deletion_at = timezone.now() + timedelta(days=30)
        self.tenant.reactivation_token = "valid-token-123"
        self.tenant.save()

        self.client.force_authenticate(user=self.owner)
        response = self.client.post(
            self.reactivate_url,
            {"token": "valid-token-123"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("message", response.data)

        # Verify tenant reactivated
        self.tenant.refresh_from_db()
        self.assertEqual(self.tenant.status, Tenant.STATUS_ACTIVE)
        self.assertIsNone(self.tenant.cancelled_at)
        self.assertIsNone(self.tenant.scheduled_deletion_at)
        self.assertIsNone(self.tenant.reactivation_token)

        # Verify email was sent
        mock_email.assert_called_once()

    def test_reactivate_requires_valid_token(self):
        """Testa que token inválido bloqueia reativação."""
        # Setup cancelled tenant
        self.tenant.status = Tenant.STATUS_CANCELLED
        self.tenant.cancelled_at = timezone.now()
        self.tenant.scheduled_deletion_at = timezone.now() + timedelta(days=30)
        self.tenant.reactivation_token = "valid-token-123"
        self.tenant.save()

        self.client.force_authenticate(user=self.owner)
        response = self.client.post(
            self.reactivate_url,
            {"token": "invalid-token"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

        # Verify tenant still cancelled
        self.tenant.refresh_from_db()
        self.assertEqual(self.tenant.status, Tenant.STATUS_CANCELLED)

    def test_reactivate_fails_after_retention_period(self):
        """Testa que não pode reativar após período de retenção."""
        # Setup cancelled tenant beyond retention
        self.tenant.status = Tenant.STATUS_CANCELLED
        self.tenant.cancelled_at = timezone.now() - timedelta(days=61)
        self.tenant.scheduled_deletion_at = timezone.now() - timedelta(days=1)
        self.tenant.reactivation_token = "valid-token-123"
        self.tenant.save()

        self.client.force_authenticate(user=self.owner)
        response = self.client.post(
            self.reactivate_url,
            {"token": "valid-token-123"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_410_GONE)

        # Verify tenant still cancelled
        self.tenant.refresh_from_db()
        self.assertEqual(self.tenant.status, Tenant.STATUS_CANCELLED)

    @patch("core.email_utils.send_account_cancellation_email")
    @patch("payments.services.SubscriptionService.cancel_tenant_subscriptions")
    def test_cancellation_calculates_deletion_date(self, mock_stripe, mock_email):
        """Testa que data de exclusão é calculada corretamente (60 dias)."""
        mock_stripe.return_value = {"success": True, "cancelled_count": 0}
        mock_email.return_value = True

        self.client.force_authenticate(user=self.owner)

        before = timezone.now()
        response = self.client.post(
            self.cancel_url,
            {
                "password": "TestPassword123!",
                "confirmation_text": "CANCELAR CONTA",
            },
            format="json",
        )
        after = timezone.now()

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        self.tenant.refresh_from_db()
        expected_min = before + timedelta(days=60)
        expected_max = after + timedelta(days=60)

        self.assertGreaterEqual(self.tenant.scheduled_deletion_at, expected_min)
        self.assertLessEqual(self.tenant.scheduled_deletion_at, expected_max)


class StripeIntegrationTest(APITestCase):
    """Tests para integração com Stripe no cancelamento."""

    def setUp(self):
        from payments.models import Subscription, PaymentCustomer

        self.tenant = Tenant.objects.create(
            name="Test Salon",
            slug="test-salon",
            status=Tenant.STATUS_ACTIVE,
        )

        self.owner = CustomUser.objects.create_user(
            username="owner",
            email="owner@example.com",
            password="password123",
            tenant=self.tenant,
        )

        # Create payment customer
        self.customer = PaymentCustomer.objects.create(
            user=self.owner, stripe_customer_id="cus_test123"
        )

        # Create active subscription
        self.subscription = Subscription.objects.create(
            user=self.owner,
            stripe_subscription_id="sub_test123",
            status="active",
            current_period_end=timezone.now() + timedelta(days=30),
        )

    @patch("stripe.Subscription.cancel")
    def test_cancel_tenant_subscriptions_success(self, mock_stripe_cancel):
        """Testa cancelamento de subscriptions no Stripe."""
        from payments.services import SubscriptionService

        mock_stripe_cancel.return_value = {"id": "sub_test123", "status": "canceled"}

        result = SubscriptionService.cancel_tenant_subscriptions(self.tenant)

        self.assertTrue(result["success"])
        self.assertEqual(result["cancelled_count"], 1)
        self.assertEqual(result["failed_count"], 0)

        # Verify subscription updated
        self.subscription.refresh_from_db()
        self.assertEqual(self.subscription.status, "canceled")

        # Verify Stripe API called
        mock_stripe_cancel.assert_called_once_with("sub_test123")

    @patch("stripe.Subscription.cancel")
    def test_cancel_tenant_subscriptions_stripe_error(self, mock_stripe_cancel):
        """Testa handling de erro do Stripe."""
        from payments.services import SubscriptionService
        import stripe

        mock_stripe_cancel.side_effect = stripe.error.StripeError("API Error")

        result = SubscriptionService.cancel_tenant_subscriptions(self.tenant)

        self.assertFalse(result["success"])
        self.assertEqual(result["cancelled_count"], 0)
        self.assertEqual(result["failed_count"], 1)
        self.assertGreater(len(result["errors"]), 0)

    def test_cancel_tenant_with_no_subscriptions(self):
        """Testa cancelamento de tenant sem subscriptions."""
        from payments.services import SubscriptionService

        # Remove subscription
        self.subscription.delete()

        result = SubscriptionService.cancel_tenant_subscriptions(self.tenant)

        self.assertTrue(result["success"])
        self.assertEqual(result["cancelled_count"], 0)
        self.assertEqual(result["failed_count"], 0)


class CeleryTasksTest(APITestCase):
    """Tests para tasks Celery de cancelamento."""

    def setUp(self):
        self.tenant = Tenant.objects.create(
            name="Test Salon",
            slug="test-salon",
            status=Tenant.STATUS_CANCELLED,
            cancelled_at=timezone.now() - timedelta(days=61),
            scheduled_deletion_at=timezone.now() - timedelta(days=1),
        )

        self.owner = CustomUser.objects.create_user(
            username="owner",
            email="owner@example.com",
            password="password123",
            tenant=self.tenant,
        )

    @patch("core.tasks.hard_delete_tenant.delay")
    def test_check_expired_cancellations(self, mock_delete_task):
        """Testa task que verifica cancelamentos expirados."""
        from core.tasks import check_expired_cancellations

        result = check_expired_cancellations()

        self.assertEqual(result["found"], 1)
        self.assertEqual(result["dispatched"], 1)
        self.assertEqual(result["errors"], 0)

        # Verify hard delete task was called
        mock_delete_task.assert_called_once_with(self.tenant.id)

    @patch("core.tasks.save_backup_locally")
    def test_hard_delete_tenant_creates_backup(self, mock_backup):
        """Testa que hard delete cria backup antes de deletar."""
        from core.tasks import hard_delete_tenant
        from pathlib import Path

        mock_backup.return_value = Path("/tmp/backup.json")

        result = hard_delete_tenant(self.tenant.id)

        self.assertTrue(result["success"])
        self.assertEqual(result["tenant_id"], self.tenant.id)

        # Verify backup was created
        mock_backup.assert_called_once()

        # Verify tenant was deleted
        self.assertFalse(Tenant.objects.filter(id=self.tenant.id).exists())

    @patch("core.email_utils.send_deletion_reminder_email")
    def test_send_deletion_reminders(self, mock_email):
        """Testa task de envio de lembretes."""
        from core.tasks import send_deletion_reminders

        # Setup tenant to be deleted in 7 days
        self.tenant.status = Tenant.STATUS_CANCELLED
        self.tenant.scheduled_deletion_at = timezone.now() + timedelta(days=7)
        self.tenant.reactivation_token = "token123"
        self.tenant.save()

        # Create staff member so owner can be found
        TenantStaffMember.objects.create(
            tenant=self.tenant, user=self.owner, role=TenantStaffMember.Role.OWNER
        )

        mock_email.return_value = True

        result = send_deletion_reminders()

        self.assertEqual(result["found"], 1)
        self.assertEqual(result["sent"], 1)
        self.assertEqual(result["errors"], 0)

        # Verify email was sent
        mock_email.assert_called_once()


class EmailNotificationsTest(APITestCase):
    """Tests para notificações por email."""

    def setUp(self):
        self.tenant = Tenant.objects.create(
            name="Test Salon",
            slug="test-salon",
            status=Tenant.STATUS_ACTIVE,
        )

        self.owner = CustomUser.objects.create_user(
            username="owner",
            email="owner@example.com",
            password="password123",
            tenant=self.tenant,
            first_name="John",
        )

    @patch("core.email_utils._send_email_safe")
    def test_send_account_cancellation_email(self, mock_send):
        """Testa envio de email de cancelamento."""
        from core.email_utils import send_account_cancellation_email

        self.tenant.cancelled_at = timezone.now()
        self.tenant.scheduled_deletion_at = timezone.now() + timedelta(days=60)

        mock_send.return_value = True

        result = send_account_cancellation_email(
            tenant=self.tenant,
            owner_user=self.owner,
            reactivation_url="https://example.com/reactivate/123/token",
        )

        self.assertTrue(result)
        mock_send.assert_called_once()

        # Verify email content
        call_args = mock_send.call_args
        subject = call_args[0][0]
        body_plain = call_args[0][1]
        body_html = call_args[0][2]
        to_email = call_args[0][3]

        self.assertIn("cancelada", subject.lower())
        self.assertIn("John", body_plain)
        self.assertIn("Test Salon", body_plain)
        self.assertIn("reativar", body_plain.lower())
        self.assertEqual(to_email, "owner@example.com")

    @patch("core.email_utils._send_email_safe")
    def test_send_deletion_reminder_email(self, mock_send):
        """Testa envio de lembrete de exclusão."""
        from core.email_utils import send_deletion_reminder_email

        self.tenant.scheduled_deletion_at = timezone.now() + timedelta(days=7)

        mock_send.return_value = True

        result = send_deletion_reminder_email(
            tenant=self.tenant,
            owner_user=self.owner,
            reactivation_url="https://example.com/reactivate/123/token",
            days_remaining=7,
        )

        self.assertTrue(result)
        mock_send.assert_called_once()

        # Verify email content
        call_args = mock_send.call_args
        subject = call_args[0][0]
        body_plain = call_args[0][1]

        self.assertIn("7 dias", subject)
        self.assertIn("excluída", subject.lower())
        self.assertIn("irreversível", body_plain.lower())

    @patch("core.email_utils._send_email_safe")
    def test_send_account_reactivation_email(self, mock_send):
        """Testa envio de email de reativação."""
        from core.email_utils import send_account_reactivation_email

        mock_send.return_value = True

        result = send_account_reactivation_email(
            tenant=self.tenant,
            owner_user=self.owner,
        )

        self.assertTrue(result)
        mock_send.assert_called_once()

        # Verify email content
        call_args = mock_send.call_args
        subject = call_args[0][0]
        body_plain = call_args[0][1]

        self.assertIn("reativada", subject.lower())
        self.assertIn("sucesso", subject.lower())
        self.assertIn("bem-vindo", body_plain.lower())
