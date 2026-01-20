import json
from decimal import Decimal
from unittest.mock import patch, MagicMock
from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth import get_user_model
from django.utils import timezone

from payments.models import PaymentCustomer
from users.models import Tenant, CommLedger

User = get_user_model()


class PlanBonusWebhookTestCase(TestCase):
    def setUp(self):
        self.client = Client()

        # Setup básico
        self.user = User.objects.create_user(
            username="test_plan_bonus",
            email="bonus@example.com",
            password="password123",
        )
        self.tenant = Tenant.objects.create(
            name="Bonus Salon",
            slug="bonus-salon",
            comm_credit_eur=Decimal("0.00"),  # Começa zerado
        )
        self.user.tenant = self.tenant
        self.user.save()

        # PaymentCustomer vinculado ao usuário
        self.pc = PaymentCustomer.objects.create(
            user=self.user, stripe_customer_id="cus_test_bonus"
        )

    @patch("stripe.Webhook.construct_event")
    @patch("stripe.Subscription.retrieve")
    def test_plan_bonus_grant_on_checkout_completed(
        self, mock_sub_retrieve, mock_construct_event
    ):
        """
        Testa se créditos são concedidos quando checkout.session.completed
        indica uma assinatura de plano com créditos (ex: Standard).
        """
        # Mock do Subscription.retrieve para quando for chamado
        mock_sub_instance = MagicMock()
        mock_sub_instance.to_dict.return_value = {
            "id": "sub_test_123",
            "status": "active",
            "trial_end": None,
            "start_date": 1700000000,
            "metadata": {"plan_code": "standard"},
            "items": {"data": [{"price": {"id": "price_standard"}}]},
        }
        # Caso o código acesse atributos direto sem to_dict
        mock_sub_instance.get.side_effect = mock_sub_instance.to_dict.return_value.get
        mock_sub_retrieve.return_value = mock_sub_instance

        # Payload do evento
        mock_event = {
            "id": "evt_test_checkout_bonus",
            "type": "checkout.session.completed",
            "data": {
                "object": {
                    "id": "cs_test_123",
                    "customer": "cus_test_bonus",
                    "subscription": "sub_test_123",
                    "mode": "subscription",
                    "metadata": {"plan_code": "standard"},
                }
            },
        }
        mock_construct_event.return_value = mock_event

        # Executar webhook
        response = self.client.post(
            reverse("payments:stripe_webhook"),
            data=json.dumps(mock_event),
            content_type="application/json",
            HTTP_STRIPE_SIGNATURE="test_sig",
        )

        self.assertEqual(response.status_code, 200)

        # Verificar se créditos foram adicionados
        # Standard tem 5.00 de créditos incluídos
        self.tenant.refresh_from_db()
        self.assertEqual(self.tenant.comm_credit_eur, Decimal("5.00"))

        # Verificar se existe registro no Ledger
        ledger_exists = CommLedger.objects.filter(
            tenant=self.tenant,
            transaction_type=CommLedger.TransactionType.BONUS,
            amount_eur=Decimal("5.00"),
        ).exists()
        self.assertTrue(ledger_exists, "Deveria existir um registro de Bônus no Ledger")

    @patch("stripe.Webhook.construct_event")
    @patch("stripe.Subscription.retrieve")
    def test_plan_bonus_grant_on_trialing(
        self, mock_sub_retrieve, mock_construct_event
    ):
        """
        Testa se créditos são concedidos também quando status é 'trialing'.
        """
        mock_sub_instance = MagicMock()
        mock_sub_instance.to_dict.return_value = {
            "id": "sub_test_trial",
            "status": "trialing",
            "trial_end": 1709999999,
            "start_date": 1700000000,
            "metadata": {"plan_code": "pro"},  # Pro tem 15.00
            "items": {"data": [{"price": {"id": "price_pro"}}]},
        }
        mock_sub_instance.get.side_effect = mock_sub_instance.to_dict.return_value.get
        mock_sub_retrieve.return_value = mock_sub_instance

        mock_event = {
            "id": "evt_test_checkout_trial",
            "type": "checkout.session.completed",
            "data": {
                "object": {
                    "id": "cs_test_trial",
                    "customer": "cus_test_bonus",
                    "subscription": "sub_test_trial",
                    "mode": "subscription",
                    "metadata": {"plan_code": "pro"},
                }
            },
        }
        mock_construct_event.return_value = mock_event

        response = self.client.post(
            reverse("payments:stripe_webhook"),
            data=json.dumps(mock_event),
            content_type="application/json",
            HTTP_STRIPE_SIGNATURE="test_sig",
        )

        self.assertEqual(response.status_code, 200)

        # Pro tem 25.00 de créditos incluídos
        self.tenant.refresh_from_db()
        self.assertEqual(self.tenant.comm_credit_eur, Decimal("25.00"))

    @patch("stripe.Webhook.construct_event")
    @patch("stripe.Subscription.retrieve")
    def test_no_double_grant(self, mock_sub_retrieve, mock_construct_event):
        """
        Testa se evita conceder créditos duas vezes para a mesma referência.
        """
        # 1. Primeira chamada (sucesso)
        mock_sub_instance = MagicMock()
        data_dict = {
            "id": "sub_test_double",
            "status": "active",
            "trial_end": None,
            "start_date": 1700000000,
            "metadata": {"plan_code": "standard"},
            "items": {"data": [{"price": {"id": "price_standard"}}]},
        }
        mock_sub_instance.to_dict.return_value = data_dict
        mock_sub_instance.get.side_effect = data_dict.get
        mock_sub_retrieve.return_value = mock_sub_instance

        mock_event = {
            "id": "evt_test_checkout_double",
            "type": "checkout.session.completed",
            "data": {
                "object": {
                    "id": "cs_test_double",
                    "customer": "cus_test_bonus",
                    "subscription": "sub_test_double",
                    "mode": "subscription",
                    "metadata": {"plan_code": "standard"},
                }
            },
        }
        mock_construct_event.return_value = mock_event

        self.client.post(
            reverse("payments:stripe_webhook"),
            data=json.dumps(mock_event),
            content_type="application/json",
            HTTP_STRIPE_SIGNATURE="test_sig",
        )

        self.tenant.refresh_from_db()
        self.assertEqual(self.tenant.comm_credit_eur, Decimal("5.00"))

        # 2. Segunda chamada (mesmo evento/assinatura)
        self.client.post(
            reverse("payments:stripe_webhook"),
            data=json.dumps(mock_event),
            content_type="application/json",
            HTTP_STRIPE_SIGNATURE="test_sig",
        )

        # Deve continuar sendo 5.00, não 10.00
        self.tenant.refresh_from_db()
        self.assertEqual(self.tenant.comm_credit_eur, Decimal("5.00"))
