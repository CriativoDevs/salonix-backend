from decimal import Decimal
from unittest.mock import MagicMock, patch
from django.urls import reverse
from django.test import override_settings
from rest_framework.test import APITestCase
from users.models import CustomUser, Tenant, TenantStaffMember
from payments.models import Subscription, PaymentCustomer


@override_settings(
    STRIPE_TRIAL_PERIOD_DAYS=14,
    STRIPE_PRICE_PRO_MONTHLY_ID="price_pro_test",
)
class CheckoutTrialTestCase(APITestCase):
    def setUp(self):
        # Create user and tenant
        self.user = CustomUser.objects.create_user(
            username="testuser",
            email="test@example.com",
            password="password123",
            first_name="Test",
            last_name="User",
        )
        self.tenant = Tenant.objects.create(name="Test Salon", slug="test-salon")
        self.user.tenant = self.tenant
        self.user.save()

        # Create staff member (owner)
        self.staff = TenantStaffMember.objects.create(
            tenant=self.tenant,
            user=self.user,
            role=TenantStaffMember.Role.OWNER,
            status=TenantStaffMember.Status.ACTIVE,
        )

        self.client.force_authenticate(user=self.user)
        self.url = reverse("payments:create_checkout_session")

        # Mock stripe
        self.patcher = patch("payments.views.stripe_utils.get_stripe")
        self.mock_get_stripe = self.patcher.start()
        self.mock_stripe = MagicMock()
        self.mock_get_stripe.return_value = self.mock_stripe

        # Mock session create
        self.mock_stripe.checkout.Session.create.return_value = MagicMock(
            url="http://checkout.url"
        )

        # Mock customer create
        self.mock_stripe.Customer.create.return_value = {"id": "cus_test_123"}

    def tearDown(self):
        self.patcher.stop()

    def test_new_customer_gets_trial(self):
        """User with no subscription history should get trial days."""
        response = self.client.post(self.url, {"plan": "basic"})
        self.assertEqual(response.status_code, 200)

        # Check call args
        _, kwargs = self.mock_stripe.checkout.Session.create.call_args
        subscription_data = kwargs.get("subscription_data", {})
        self.assertEqual(subscription_data.get("trial_period_days"), 14)

    def test_active_subscription_no_trial(self):
        """User with active subscription should NOT get trial."""
        Subscription.objects.create(
            user=self.user, stripe_subscription_id="sub_active", status="active"
        )

        response = self.client.post(self.url, {"plan": "basic"})
        self.assertEqual(response.status_code, 200)

        _, kwargs = self.mock_stripe.checkout.Session.create.call_args
        subscription_data = kwargs.get("subscription_data", {})
        self.assertNotIn("trial_period_days", subscription_data)
        self.assertFalse(subscription_data.get("trial_from_plan", True))

    def test_canceled_subscription_no_trial(self):
        """User with canceled subscription should NOT get trial."""
        Subscription.objects.create(
            user=self.user, stripe_subscription_id="sub_canceled", status="canceled"
        )

        response = self.client.post(self.url, {"plan": "basic"})
        self.assertEqual(response.status_code, 200)

        _, kwargs = self.mock_stripe.checkout.Session.create.call_args
        subscription_data = kwargs.get("subscription_data", {})
        self.assertNotIn("trial_period_days", subscription_data)

    def test_incomplete_subscription_gets_trial(self):
        """User with only incomplete subscription SHOULD get trial."""
        Subscription.objects.create(
            user=self.user, stripe_subscription_id="sub_incomplete", status="incomplete"
        )

        response = self.client.post(self.url, {"plan": "basic"})
        self.assertEqual(response.status_code, 200)

        _, kwargs = self.mock_stripe.checkout.Session.create.call_args
        subscription_data = kwargs.get("subscription_data", {})

        # This is expected to fail before the fix
        self.assertEqual(subscription_data.get("trial_period_days"), 14)
