import json
from decimal import Decimal
from unittest.mock import patch, MagicMock
from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient
from django.contrib.auth import get_user_model
from users.models import Tenant, TenantStaffMember

User = get_user_model()
from payments.models import PaymentCustomer
from users.services import FounderService


class FounderCheckoutTest(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(
            username="owner", email="owner@example.com", password="password"
        )
        self.tenant = Tenant.objects.create(
            name="Test Salon", slug="test-salon", is_founder=False
        )
        self.user.tenant = self.tenant
        self.user.save()

        self.staff = TenantStaffMember.objects.create(
            user=self.user,
            tenant=self.tenant,
            role=TenantStaffMember.Role.OWNER,
            status=TenantStaffMember.Status.ACTIVE,
        )

        # Payment Customer
        self.pc = PaymentCustomer.objects.create(
            user=self.user, stripe_customer_id="cus_test123"
        )

        self.client.force_authenticate(user=self.user)

    @patch("payments.views.stripe_utils.get_stripe")
    @patch("payments.views.stripe_utils.get_price_id_for_plan")
    @patch("users.services.FounderService.can_assign_founder")
    def test_create_checkout_session_founder_allowed(
        self, mock_can_assign, mock_get_price, mock_get_stripe
    ):
        mock_can_assign.return_value = True
        mock_get_price.return_value = "price_founder_123"

        mock_stripe = MagicMock()
        mock_session = MagicMock()
        mock_session.url = "http://checkout.url"
        mock_stripe.checkout.Session.create.return_value = mock_session
        mock_get_stripe.return_value = mock_stripe

        url = reverse("payments:create_checkout_session")
        data = {"plan": "founder"}

        response = self.client.post(url, data)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["checkout_url"], "http://checkout.url")

        # Verify metadata
        args, kwargs = mock_stripe.checkout.Session.create.call_args
        self.assertEqual(kwargs["metadata"]["plan_code"], "founder")

    @patch("payments.views.stripe_utils.get_stripe")
    @patch("payments.views.stripe_utils.get_price_id_for_plan")
    @patch("users.services.FounderService.can_assign_founder")
    def test_create_checkout_session_founder_annual(
        self, mock_can_assign, mock_get_price, mock_get_stripe
    ):
        mock_can_assign.return_value = True
        mock_get_price.return_value = "price_founder_yearly_123"

        mock_stripe = MagicMock()
        mock_session = MagicMock()
        mock_session.url = "http://checkout.url"
        mock_stripe.checkout.Session.create.return_value = mock_session
        mock_get_stripe.return_value = mock_stripe

        url = reverse("payments:create_checkout_session")
        data = {"plan": "founder", "interval": "annual"}

        response = self.client.post(url, data)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["checkout_url"], "http://checkout.url")

        # Verify get_price_id_for_plan was called with interval='annual'
        mock_get_price.assert_called_with("founder", interval="annual")

    @patch("payments.views.stripe_utils.get_stripe")
    @patch("users.services.FounderService.can_assign_founder")
    def test_create_checkout_session_founder_denied(
        self, mock_can_assign, mock_get_stripe
    ):
        mock_can_assign.return_value = False

        url = reverse("payments:create_checkout_session")
        data = {"plan": "founder"}

        response = self.client.post(url, data)

        self.assertEqual(response.status_code, 400)
        self.assertIn("não está mais disponível", response.data["detail"])

    @patch("payments.views.stripe_utils.get_stripe")
    @patch("payments.views.stripe_utils.get_price_id_for_plan")
    @patch("users.services.FounderService.get_availability")
    def test_create_checkout_session_basic_blocked_when_founder_available(
        self, mock_availability, mock_get_price, mock_get_stripe
    ):
        mock_availability.return_value = {
            "total_limit": 500,
            "used_count": 0,
            "remaining_count": 500,
        }

        url = reverse("payments:create_checkout_session")
        response = self.client.post(url, {"plan": "basic"})

        self.assertEqual(response.status_code, 400)
        self.assertIn("Founder", response.data["detail"])
        mock_get_price.assert_not_called()

    @patch("payments.views.stripe_utils.get_stripe")
    @patch("payments.views.stripe_utils.get_price_id_for_plan")
    @patch("users.services.FounderService.get_availability")
    def test_create_checkout_session_basic_allowed_when_founder_exhausted(
        self, mock_availability, mock_get_price, mock_get_stripe
    ):
        mock_availability.return_value = {
            "total_limit": 500,
            "used_count": 500,
            "remaining_count": 0,
        }
        mock_get_price.return_value = "price_basic_123"

        mock_stripe = MagicMock()
        mock_session = MagicMock()
        mock_session.url = "http://checkout.url"
        mock_stripe.checkout.Session.create.return_value = mock_session
        mock_get_stripe.return_value = mock_stripe

        url = reverse("payments:create_checkout_session")
        response = self.client.post(url, {"plan": "basic"})

        self.assertEqual(response.status_code, 200)

    @patch("payments.views.stripe_utils.get_stripe")
    @patch("payments.views.stripe_utils.get_price_id_for_plan")
    @patch("users.services.FounderService.get_availability")
    def test_create_checkout_session_basic_allowed_for_active_founder_tenant(
        self, mock_availability, mock_get_price, mock_get_stripe
    ):
        # Vagas Founder ainda existem, mas o tenant JÁ É founder — deve poder
        # fazer downgrade voluntário para Basic sem bloqueio.
        mock_availability.return_value = {
            "total_limit": 500,
            "used_count": 1,
            "remaining_count": 499,
        }
        mock_get_price.return_value = "price_basic_123"

        self.tenant.is_founder = True
        self.tenant.save()

        mock_stripe = MagicMock()
        mock_session = MagicMock()
        mock_session.url = "http://checkout.url"
        mock_stripe.checkout.Session.create.return_value = mock_session
        mock_get_stripe.return_value = mock_stripe

        url = reverse("payments:create_checkout_session")
        response = self.client.post(url, {"plan": "basic"})

        self.assertEqual(response.status_code, 200)

    @patch("payments.views.stripe.Subscription.retrieve")
    @patch("payments.views.stripe.Webhook.construct_event")
    @patch("payments.views.stripe_utils.get_stripe")
    def test_webhook_promotes_founder(
        self, mock_get_stripe, mock_construct_event, mock_retrieve
    ):
        # Simulate checkout.session.completed event for founder plan
        payload = {
            "id": "evt_test123",
            "type": "checkout.session.completed",
            "data": {
                "object": {
                    "id": "cs_test123",
                    "customer": "cus_test123",
                    "mode": "subscription",
                    "subscription": "sub_test123",
                    "metadata": {"plan_code": "founder", "user_id": str(self.user.id)},
                }
            },
        }

        # Mock event object properly to simulate Stripe object behavior
        mock_event = MagicMock()
        mock_event.id = "evt_test123"
        mock_event.type = "checkout.session.completed"
        # The view accesses event["id"], event["type"], event["data"]["object"]
        # so we need to support item access on the mock
        mock_event.__getitem__.side_effect = lambda key: {
            "id": "evt_test123",
            "type": "checkout.session.completed",
            "data": payload["data"],
        }[key]

        # Also need to handle event.get("data", {})
        mock_event.get.side_effect = lambda key, default=None: {
            "data": payload["data"]
        }.get(key, default)

        mock_construct_event.return_value = mock_event

        # Mock subscription retrieval
        mock_retrieve.return_value = {
            "id": "sub_test123",
            "status": "active",
            "metadata": {"plan_code": "founder"},
            "items": {"data": [{"price": {"id": "price_founder"}}]},
        }

        url = reverse("payments:stripe_webhook")
        response = self.client.post(
            url, json.dumps(payload), content_type="application/json"
        )

        self.assertEqual(response.status_code, 200)

        # Check tenant updated
        self.tenant.refresh_from_db()
        self.assertTrue(self.tenant.is_founder)
        self.assertEqual(self.tenant.plan_tier, "basic")

    @patch("payments.views.stripe.Subscription.retrieve")
    @patch("payments.views.stripe.Webhook.construct_event")
    @patch("payments.views.stripe_utils.get_stripe")
    def test_webhook_standard_plan(
        self, mock_get_stripe, mock_construct_event, mock_retrieve
    ):
        # Simulate checkout.session.completed event for standard plan
        payload = {
            "id": "evt_test456",
            "type": "checkout.session.completed",
            "data": {
                "object": {
                    "id": "cs_test456",
                    "customer": "cus_test123",
                    "mode": "subscription",
                    "subscription": "sub_test456",
                    "metadata": {"plan_code": "standard", "user_id": str(self.user.id)},
                }
            },
        }

        # Mock event object properly to simulate Stripe object behavior
        mock_event = MagicMock()
        mock_event.id = "evt_test456"
        mock_event.type = "checkout.session.completed"
        # The view accesses event["id"], event["type"], event["data"]["object"]
        # so we need to support item access on the mock
        mock_event.__getitem__.side_effect = lambda key: {
            "id": "evt_test456",
            "type": "checkout.session.completed",
            "data": payload["data"],
        }[key]

        # Also need to handle event.get("data", {})
        mock_event.get.side_effect = lambda key, default=None: {
            "data": payload["data"]
        }.get(key, default)

        mock_construct_event.return_value = mock_event

        # Mock subscription retrieval
        mock_retrieve.return_value = {
            "id": "sub_test456",
            "status": "active",
            "metadata": {"plan_code": "standard"},
            "items": {"data": [{"price": {"id": "price_standard"}}]},
        }

        url = reverse("payments:stripe_webhook")
        response = self.client.post(
            url, json.dumps(payload), content_type="application/json"
        )

        self.assertEqual(response.status_code, 200)

        # Check tenant updated
        self.tenant.refresh_from_db()
        self.assertFalse(self.tenant.is_founder)  # Should remain False
        self.assertEqual(self.tenant.plan_tier, "standard")

    @patch("payments.views.stripe_utils.get_plan_code_from_price")
    @patch("payments.views.stripe.Webhook.construct_event")
    def test_webhook_subscription_deleted_removes_founder_status(
        self, mock_construct_event, mock_get_plan
    ):
        """
        Testa que customer.subscription.deleted remove is_founder quando tenant é Founder.
        Regra 6 de founderplan.md: "O status Founder é perdido definitivamente"
        """
        # Setup: Tenant é Founder ativo
        self.tenant.is_founder = True
        self.tenant.plan_tier = "founder"
        self.tenant.save()

        # Mock get_plan_code_from_price para retornar "founder"
        mock_get_plan.return_value = "founder"

        # Payload do evento customer.subscription.deleted
        payload = {
            "id": "evt_deleted_123",
            "type": "customer.subscription.deleted",
            "data": {
                "object": {
                    "id": "sub_founder_123",
                    "customer": "cus_test123",
                    "status": "canceled",
                    "metadata": {"plan_code": "founder", "user_id": str(self.user.id)},
                    "items": {"data": [{"price": {"id": "price_founder_123"}}]},
                }
            },
        }

        # Mock event
        mock_event = MagicMock()
        mock_event.__getitem__.side_effect = payload.__getitem__
        mock_event.get.side_effect = lambda key, default=None: payload.get(key, default)
        mock_construct_event.return_value = mock_event

        # Chamar webhook
        url = reverse("payments:stripe_webhook")
        response = self.client.post(
            url, json.dumps(payload), content_type="application/json"
        )

        self.assertEqual(response.status_code, 200)

        # Verificar que is_founder foi removido
        self.tenant.refresh_from_db()
        self.assertFalse(
            self.tenant.is_founder,
            "is_founder deve ser False após subscription.deleted de plano Founder",
        )

    @patch("payments.views.stripe_utils.get_plan_code_from_price")
    @patch("payments.views.stripe.Webhook.construct_event")
    def test_webhook_subscription_deleted_preserves_non_founder(
        self, mock_construct_event, mock_get_plan
    ):
        """
        Testa que customer.subscription.deleted NÃO remove is_founder se o plano não for Founder.
        """
        # Setup: Tenant NÃO é Founder (mas tem outro plano)
        self.tenant.is_founder = False
        self.tenant.plan_tier = "basic"
        self.tenant.save()

        # Mock get_plan_code_from_price para retornar "basic"
        mock_get_plan.return_value = "basic"

        # Payload do evento customer.subscription.deleted
        payload = {
            "id": "evt_deleted_456",
            "type": "customer.subscription.deleted",
            "data": {
                "object": {
                    "id": "sub_basic_456",
                    "customer": "cus_test123",
                    "status": "canceled",
                    "metadata": {"plan_code": "basic", "user_id": str(self.user.id)},
                    "items": {"data": [{"price": {"id": "price_basic_123"}}]},
                }
            },
        }

        # Mock event
        mock_event = MagicMock()
        mock_event.__getitem__.side_effect = payload.__getitem__
        mock_event.get.side_effect = lambda key, default=None: payload.get(key, default)
        mock_construct_event.return_value = mock_event

        # Chamar webhook
        url = reverse("payments:stripe_webhook")
        response = self.client.post(
            url, json.dumps(payload), content_type="application/json"
        )

        self.assertEqual(response.status_code, 200)

        # Verificar que is_founder permanece False (não foi tocado)
        self.tenant.refresh_from_db()
        self.assertFalse(self.tenant.is_founder)
