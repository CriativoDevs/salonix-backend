import pytest
from core.serializers import PublicClientRegistrationSerializer


@pytest.mark.django_db
class TestPublicClientRegistrationSerializer:
    def test_valid_with_email_only(self):
        serializer = PublicClientRegistrationSerializer(
            data={"name": "Maria Silva", "email": "maria@example.com"}
        )
        assert serializer.is_valid(), serializer.errors
        assert serializer.validated_data["email"] == "maria@example.com"

    def test_valid_with_phone_only(self):
        serializer = PublicClientRegistrationSerializer(
            data={"name": "João Costa", "phone_number": "+351912345678"}
        )
        assert serializer.is_valid(), serializer.errors

    def test_missing_name_is_invalid(self):
        serializer = PublicClientRegistrationSerializer(
            data={"email": "maria@example.com"}
        )
        assert not serializer.is_valid()
        assert "name" in serializer.errors

    def test_missing_email_and_phone_is_invalid(self):
        serializer = PublicClientRegistrationSerializer(data={"name": "Maria Silva"})
        assert not serializer.is_valid()

    def test_email_is_normalized_to_lowercase(self):
        serializer = PublicClientRegistrationSerializer(
            data={"name": "Maria Silva", "email": "Maria@Example.COM"}
        )
        assert serializer.is_valid(), serializer.errors
        assert serializer.validated_data["email"] == "maria@example.com"


from unittest.mock import patch
from django.test import override_settings
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient
from users.models import Tenant
from core.models import SalonCustomer


@pytest.mark.django_db
class TestPublicClientRegistrationView:
    def setup_method(self):
        self.client = APIClient()
        self.tenant = Tenant.objects.create(
            name="Salão Teste",
            slug="salao-teste",
            plan_tier=Tenant.PLAN_BASIC,
            pwa_client_enabled=True,
            is_active=True,
        )
        self.url = reverse(
            "public_client_registration", kwargs={"tenant_slug": self.tenant.slug}
        )

    @patch("core.views.send_customer_pwa_invite")
    def test_valid_registration_creates_customer_and_sends_invite(self, mock_send):
        mock_send.return_value = True
        response = self.client.post(
            self.url,
            {"name": "Maria Silva", "email": "maria@example.com"},
            format="json",
        )
        assert response.status_code == status.HTTP_201_CREATED
        assert "customer_id" in response.data

        customer = SalonCustomer.objects.get(tenant=self.tenant, email="maria@example.com")
        assert customer.name == "Maria Silva"
        mock_send.assert_called_once()
        _, kwargs = mock_send.call_args
        assert kwargs["tenant"] == self.tenant
        assert kwargs["customer"] == customer
        assert kwargs["invited_by"] is None

    def test_tenant_not_found_returns_404(self):
        url = reverse(
            "public_client_registration", kwargs={"tenant_slug": "does-not-exist"}
        )
        response = self.client.post(url, {"name": "Maria Silva", "email": "m@x.com"})
        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_inactive_tenant_returns_404(self):
        self.tenant.is_active = False
        self.tenant.save()
        response = self.client.post(self.url, {"name": "Maria Silva", "email": "m@x.com"})
        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_tenant_without_pwa_client_returns_404(self):
        self.tenant.pwa_client_enabled = False
        self.tenant.plan_tier = Tenant.PLAN_BASIC
        self.tenant.save()
        response = self.client.post(self.url, {"name": "Maria Silva", "email": "m@x.com"})
        assert response.status_code == status.HTTP_404_NOT_FOUND

    @patch("core.views.send_customer_pwa_invite")
    def test_duplicate_email_same_tenant_returns_400(self, mock_send):
        mock_send.return_value = True
        SalonCustomer.objects.create(
            tenant=self.tenant, name="Existing", email="maria@example.com"
        )
        response = self.client.post(
            self.url, {"name": "Maria Silva", "email": "maria@example.com"}
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        mock_send.assert_not_called()

    @patch("core.views.send_customer_pwa_invite")
    def test_duplicate_email_case_insensitive(self, mock_send):
        mock_send.return_value = True
        SalonCustomer.objects.create(
            tenant=self.tenant, name="Existing", email="maria@example.com"
        )
        response = self.client.post(
            self.url, {"name": "Maria Silva", "email": "Maria@Example.com"}
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    @patch("core.views.send_customer_pwa_invite")
    def test_same_email_different_tenants_allowed(self, mock_send):
        mock_send.return_value = True
        other_tenant = Tenant.objects.create(
            name="Outro Salão",
            slug="outro-salao",
            plan_tier=Tenant.PLAN_BASIC,
            pwa_client_enabled=True,
            is_active=True,
        )
        SalonCustomer.objects.create(
            tenant=other_tenant, name="Existing", email="maria@example.com"
        )
        response = self.client.post(
            self.url, {"name": "Maria Silva", "email": "maria@example.com"}
        )
        assert response.status_code == status.HTTP_201_CREATED

    @patch("core.views.send_customer_pwa_invite")
    def test_invite_dispatch_failure_still_creates_customer(self, mock_send):
        mock_send.side_effect = Exception("SMTP down")
        response = self.client.post(
            self.url, {"name": "Maria Silva", "email": "maria@example.com"}
        )
        assert response.status_code == status.HTTP_201_CREATED
        assert SalonCustomer.objects.filter(
            tenant=self.tenant, email="maria@example.com"
        ).exists()

    def test_missing_name_returns_400(self):
        response = self.client.post(self.url, {"email": "maria@example.com"})
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    @override_settings(CAPTCHA_ENABLED=True, CAPTCHA_BYPASS_TOKEN="")
    def test_invalid_captcha_returns_400(self):
        response = self.client.post(
            self.url, {"name": "Maria Silva", "email": "maria@example.com"}
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    @patch("core.views.send_customer_pwa_invite")
    @override_settings(CAPTCHA_ENABLED=True, CAPTCHA_BYPASS_TOKEN="dev-bypass")
    def test_captcha_bypass_token_allows_registration(self, mock_send):
        mock_send.return_value = True
        response = self.client.post(
            self.url,
            {
                "name": "Maria Silva",
                "email": "maria@example.com",
                "captcha_value": "dev-bypass",
            },
        )
        assert response.status_code == status.HTTP_201_CREATED

    @patch("core.views.send_customer_pwa_invite")
    @override_settings(
        REST_FRAMEWORK={
            "DEFAULT_THROTTLE_CLASSES": [
                "rest_framework.throttling.ScopedRateThrottle",
            ],
            "DEFAULT_THROTTLE_RATES": {"clients_registration": "2/hour"},
        },
    )
    def test_rate_limit_returns_429(self, mock_send):
        mock_send.return_value = True
        from django.core.cache import cache

        cache.clear()
        self.client.post(self.url, {"name": "A", "email": "a1@example.com"})
        self.client.post(self.url, {"name": "B", "email": "a2@example.com"})
        response = self.client.post(self.url, {"name": "C", "email": "a3@example.com"})
        assert response.status_code == status.HTTP_429_TOO_MANY_REQUESTS
