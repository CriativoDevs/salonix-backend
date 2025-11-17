import json
from decimal import Decimal
from django.test import TestCase, Client
from django.urls import reverse
from django.conf import settings
from unittest.mock import patch
from django.contrib.auth import get_user_model

from payments.models import CreditPayment, StripeWebhookEvent
from users.models import Tenant

User = get_user_model()


class CreditWebhookTestCase(TestCase):
    """Testes para webhooks de pagamentos de créditos."""

    def setUp(self):
        """Configurar dados de teste."""
        self.client = Client()

        # Criar usuário e tenant
        self.user = User.objects.create_user(
            username="testuser",
            email="test@example.com",
            password="testpass123",
            first_name="Test",
            last_name="User",
        )

        self.tenant = Tenant.objects.create(name="Test Salon", slug="test-salon")

        # Criar pagamento de crédito
        self.credit_payment = CreditPayment.objects.create(
            user=self.user,
            tenant=self.tenant,
            stripe_payment_intent_id="pi_test_123456",
            stripe_customer_id="cus_test_123",
            stripe_price_id=settings.STRIPE_PRICE_CREDITS_10_ID,
            amount=Decimal("10.00"),
            credits_purchased=Decimal("10.00"),
            status="pending",
        )

    @patch("stripe.Webhook.construct_event")
    def test_payment_intent_succeeded_webhook(self, mock_construct_event):
        """Testa webhook de pagamento bem-sucedido."""
        # Mock do evento do Stripe
        mock_event = {
            "id": "evt_test_webhook",
            "type": "payment_intent.succeeded",
            "data": {
                "object": {
                    "id": "pi_test_123456",
                    "status": "succeeded",
                    "amount": 1000,  # €10.00 em centavos
                    "currency": "eur",
                }
            },
        }
        mock_construct_event.return_value = mock_event

        # Fazer requisição para o webhook
        response = self.client.post(
            reverse("payments:stripe_webhook"),
            data=json.dumps(mock_event),
            content_type="application/json",
            HTTP_STRIPE_SIGNATURE="test_signature",
        )

        # Verificar resposta
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Webhook processed successfully")

        # Verificar se o pagamento foi atualizado
        self.credit_payment.refresh_from_db()
        self.assertEqual(self.credit_payment.status, "succeeded")
        self.assertTrue(self.credit_payment.credits_applied)
        self.assertIsNotNone(self.credit_payment.completed_at)

        # Verificar se os créditos foram aplicados ao tenant
        self.tenant.refresh_from_db()
        self.assertEqual(self.tenant.comm_credit_eur, Decimal("10.00"))

        # Verificar se o evento foi registrado
        webhook_event = StripeWebhookEvent.objects.get(
            stripe_event_id="evt_test_webhook"
        )
        self.assertTrue(webhook_event.processed)
        self.assertIsNotNone(webhook_event.processed_at)

    @patch("stripe.Webhook.construct_event")
    def test_payment_intent_failed_webhook(self, mock_construct_event):
        """Testa webhook de pagamento falhado."""
        # Mock do evento do Stripe
        mock_event = {
            "id": "evt_test_webhook_failed",
            "type": "payment_intent.payment_failed",
            "data": {
                "object": {
                    "id": "pi_test_123456",
                    "status": "failed",
                    "amount": 1000,
                    "currency": "eur",
                }
            },
        }
        mock_construct_event.return_value = mock_event

        # Fazer requisição para o webhook
        response = self.client.post(
            reverse("payments:stripe_webhook"),
            data=json.dumps(mock_event),
            content_type="application/json",
            HTTP_STRIPE_SIGNATURE="test_signature",
        )

        # Verificar resposta
        self.assertEqual(response.status_code, 200)

        # Verificar se o pagamento foi atualizado
        self.credit_payment.refresh_from_db()
        self.assertEqual(self.credit_payment.status, "failed")
        self.assertFalse(self.credit_payment.credits_applied)
        self.assertIsNotNone(self.credit_payment.completed_at)

        # Verificar se os créditos NÃO foram aplicados ao tenant
        self.tenant.refresh_from_db()
        self.assertEqual(self.tenant.comm_credit_eur, Decimal("0.00"))

    @patch("stripe.Webhook.construct_event")
    def test_duplicate_webhook_processing(self, mock_construct_event):
        """Testa que webhooks duplicados não são processados duas vezes."""
        # Mock do evento do Stripe
        mock_event = {
            "id": "evt_test_duplicate",
            "type": "payment_intent.succeeded",
            "data": {
                "object": {
                    "id": "pi_test_123456",
                    "status": "succeeded",
                    "amount": 1000,
                    "currency": "eur",
                }
            },
        }
        mock_construct_event.return_value = mock_event

        # Primeira requisição
        response1 = self.client.post(
            reverse("payments:stripe_webhook"),
            data=json.dumps(mock_event),
            content_type="application/json",
            HTTP_STRIPE_SIGNATURE="test_signature",
        )
        self.assertEqual(response1.status_code, 200)

        # Verificar créditos aplicados
        self.tenant.refresh_from_db()
        self.assertEqual(self.tenant.comm_credit_eur, Decimal("10.00"))

        # Segunda requisição (duplicada)
        response2 = self.client.post(
            reverse("payments:stripe_webhook"),
            data=json.dumps(mock_event),
            content_type="application/json",
            HTTP_STRIPE_SIGNATURE="test_signature",
        )
        self.assertEqual(response2.status_code, 200)
        self.assertContains(response2, "Event already processed")

        # Verificar que os créditos não foram aplicados novamente
        self.tenant.refresh_from_db()
        self.assertEqual(
            self.tenant.comm_credit_eur, Decimal("10.00")
        )  # Ainda 10, não 20

    @patch("stripe.Webhook.construct_event")
    def test_webhook_payment_not_found(self, mock_construct_event):
        """Testa webhook para pagamento que não existe no banco."""
        # Mock do evento do Stripe
        mock_event = {
            "id": "evt_test_not_found",
            "type": "payment_intent.succeeded",
            "data": {
                "object": {
                    "id": "pi_not_found_123",  # ID que não existe
                    "status": "succeeded",
                    "amount": 1000,
                    "currency": "eur",
                }
            },
        }
        mock_construct_event.return_value = mock_event

        # Fazer requisição para o webhook
        response = self.client.post(
            reverse("payments:stripe_webhook"),
            data=json.dumps(mock_event),
            content_type="application/json",
            HTTP_STRIPE_SIGNATURE="test_signature",
        )

        # Verificar que retorna erro
        self.assertEqual(response.status_code, 400)
        self.assertContains(response, "Error processing webhook", status_code=400)

        # Verificar que o evento foi registrado com erro
        webhook_event = StripeWebhookEvent.objects.get(
            stripe_event_id="evt_test_not_found"
        )
        self.assertFalse(webhook_event.processed)
        self.assertIsNotNone(webhook_event.processing_error)
        self.assertIn("Payment not found", webhook_event.processing_error)
