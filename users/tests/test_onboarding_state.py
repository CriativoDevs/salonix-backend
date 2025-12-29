import pytest
from rest_framework import status
from rest_framework.test import APIClient
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
