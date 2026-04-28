import pytest
from datetime import timedelta
from rest_framework import status
from rest_framework.test import APIClient
from django.utils import timezone
from users.models import CustomUser, Tenant


@pytest.mark.django_db
class TestOnboardingState:
    def setup_method(self):
        self.client = APIClient()
        self.url = "/api/users/me/profile/"
        self.tenant = Tenant.objects.create(
            name="Test Tenant", slug="test-tenant", plan_tier="scale"
        )
        self.user = CustomUser.objects.create(
            email="user@test.com", username="user@test.com", tenant=self.tenant
        )
        self.client.force_authenticate(user=self.user)

    def test_get_initial_onboarding_status(self):
        """Verify initial onboarding status is empty dict"""
        response = self.client.get(self.url)
        assert response.status_code == status.HTTP_200_OK
        assert response.data["onboarding_status"] == {}

    def test_patch_update_onboarding_status(self):
        """Verify updating specific flags in onboarding status"""
        payload = {"onboarding_status": {"first_login": False, "tour_seen": True}}
        response = self.client.patch(self.url, payload, format="json")
        assert response.status_code == status.HTTP_200_OK
        assert response.data["onboarding_status"]["first_login"] is False
        assert response.data["onboarding_status"]["tour_seen"] is True

    def test_patch_merge_onboarding_status(self):
        """Verify that updates merge with existing data rather than replacing it"""
        # Set initial state
        self.user.onboarding_status = {"first_login": False}
        self.user.save()

        # Update a different key
        payload = {"onboarding_status": {"setup_completed": True}}
        response = self.client.patch(self.url, payload, format="json")

        assert response.status_code == status.HTTP_200_OK
        # Check that old key is preserved and new key is added
        assert response.data["onboarding_status"]["first_login"] is False
        assert response.data["onboarding_status"]["setup_completed"] is True

    def test_patch_invalid_format(self):
        """Verify error when sending non-dict onboarding status"""
        payload = {"onboarding_status": "invalid_string"}
        response = self.client.patch(self.url, payload, format="json")
        assert response.status_code == status.HTTP_400_BAD_REQUEST


@pytest.mark.django_db
class TestBillingState:
    def setup_method(self):
        from django.core.cache import cache

        cache.clear()
        self.client = APIClient()
        self.url = "/api/users/me/tenant/"
        self.tenant = Tenant.objects.create(
            name="Test Tenant", slug="test-billing", plan_tier="scale"
        )
        self.user = CustomUser.objects.create(
            email="owner@billing.com", username="owner@billing.com", tenant=self.tenant
        )
        self.client.force_authenticate(user=self.user)

    def test_billing_pending_false_initially(self):
        """Verify billing_pending is false when no subscription exists"""
        response = self.client.get(self.url)
        assert response.status_code == status.HTTP_200_OK
        assert response.data["billing_pending"] is False

    def test_billing_pending_true_past_due(self):
        """Verify billing_pending is true when subscription is past_due"""
        # Need to import Subscription dynamically or at top if available
        from payments.models import Subscription

        Subscription.objects.create(
            user=self.user,
            stripe_subscription_id="sub_past_due",
            status="past_due",
            price_id="price_fake",
        )
        response = self.client.get(self.url)
        assert response.status_code == status.HTTP_200_OK
        assert response.data["billing_pending"] is True

    def test_billing_pending_false_active(self):
        """Verify billing_pending is false when subscription is active"""
        from payments.models import Subscription

        Subscription.objects.create(
            user=self.user, stripe_subscription_id="sub_active", status="active"
        )
        response = self.client.get(self.url)
        assert response.status_code == status.HTTP_200_OK
        assert response.data["billing_pending"] is False

    def test_me_tenant_promotional_skips_subscription_sync(self, monkeypatch):
        """Tenant promocional não deve reconciliar plano com Stripe no bootstrap."""
        self.tenant.billing_mode = Tenant.BILLING_MODE_PROMOTIONAL
        self.tenant.save(update_fields=["billing_mode", "updated_at"])

        from payments.services import SubscriptionService

        def _should_not_be_called(_user):
            raise AssertionError(
                "SubscriptionService.get_current_subscription should not be called"
            )

        monkeypatch.setattr(
            SubscriptionService,
            "get_current_subscription",
            _should_not_be_called,
        )

        response = self.client.get(self.url)
        assert response.status_code == status.HTTP_200_OK

    def test_me_tenant_applies_due_promotional_transition(self):
        self.tenant.plan_tier = Tenant.PLAN_PRO
        self.tenant.billing_mode = Tenant.BILLING_MODE_PROMOTIONAL
        self.tenant.promotional_expires_at = timezone.now() - timedelta(hours=1)
        self.tenant.promotional_converts_to_plan = Tenant.PLAN_BASIC
        self.tenant.save(
            update_fields=[
                "plan_tier",
                "billing_mode",
                "promotional_expires_at",
                "promotional_converts_to_plan",
                "updated_at",
            ]
        )

        response = self.client.get(self.url)
        assert response.status_code == status.HTTP_200_OK

        self.tenant.refresh_from_db()
        assert self.tenant.billing_mode == Tenant.BILLING_MODE_STRIPE
        assert self.tenant.plan_tier == Tenant.PLAN_BASIC
        assert self.tenant.promotional_expires_at is None

    @pytest.mark.parametrize(
        ("app_type", "flag_field"),
        (("admin", "rn_admin_enabled"), ("client", "rn_client_enabled")),
    )
    def test_me_tenant_mobile_promotional_bootstrap_without_subscription(
        self, monkeypatch, app_type, flag_field
    ):
        setattr(self.tenant, flag_field, True)
        self.tenant.billing_mode = Tenant.BILLING_MODE_PROMOTIONAL
        self.tenant.save(update_fields=[flag_field, "billing_mode", "updated_at"])

        from payments.services import SubscriptionService

        def _should_not_be_called(_user):
            raise AssertionError(
                "SubscriptionService.get_current_subscription should not be called"
            )

        monkeypatch.setattr(
            SubscriptionService,
            "get_current_subscription",
            _should_not_be_called,
        )

        response = self.client.get(self.url, HTTP_X_APP_TYPE=app_type)

        assert response.status_code == status.HTTP_200_OK
        assert response.data["plan"]["billing_mode"] == Tenant.BILLING_MODE_PROMOTIONAL
