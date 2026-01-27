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
