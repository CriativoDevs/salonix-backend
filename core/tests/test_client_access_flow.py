import pytest
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient
from django.utils import timezone
from django.core import signing
from unittest.mock import patch
from users.models import Tenant
from core.models import SalonCustomer
from core.utils.client_access import (
    create_client_access_data,
    generate_client_access_token,
)


@pytest.mark.django_db
class TestClientAccessFlow:
    def setup_method(self):
        self.tenant = Tenant.objects.create(
            name="Test Salon",
            slug="test-salon",
            plan_tier=Tenant.PLAN_BASIC,
            pwa_client_enabled=True,
        )
        self.customer = SalonCustomer.objects.create(
            tenant=self.tenant,
            name="Test Client",
            email="client@test.com",
        )
        self.client = APIClient()

    def test_create_client_access_data_structure(self):
        payload, token, link = create_client_access_data(self.tenant, self.customer)

        assert payload["tenant_id"] == self.tenant.id
        assert payload["customer_id"] == self.customer.id
        assert "ts" in payload
        assert "jti" in payload
        assert len(payload["jti"]) > 0

        # Verify token signature
        decoded = signing.loads(token, salt="CLIENT_PWA_INVITE_SALT")
        assert decoded == payload

        # Verify link format
        assert f"token={token}" in link
        assert f"tenant={self.tenant.slug}" in link

    def test_accept_valid_token(self):
        _, token, _ = create_client_access_data(self.tenant, self.customer)

        url = reverse("clients_access_accept")
        response = self.client.post(url, {"token": token}, format="json")

        assert response.status_code == status.HTTP_200_OK
        # JWT tokens in response
        assert "access" in response.data
        assert "refresh" in response.data
        assert response.data["tenant_id"] == self.tenant.id
        assert response.data["customer_id"] == self.customer.id
        assert "has_password" in response.data

    def test_accept_expired_token(self):
        # Create a payload with old timestamp
        payload = {
            "tenant_id": self.tenant.id,
            "customer_id": self.customer.id,
            "ts": int((timezone.now() - timezone.timedelta(days=1)).timestamp()),
            "jti": "expired_jti",
        }
        token = generate_client_access_token(payload)

        url = reverse("clients_access_accept")
        response = self.client.post(url, {"token": token}, format="json")

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        # Depending on implementation, it might say "Token expirado" or similar validation error
        # Checking status 400 is enough for now, but checking content is better.

    def test_accept_invalid_token_signature(self):
        token = "invalid.token.signature"
        url = reverse("clients_access_accept")
        response = self.client.post(url, {"token": token}, format="json")

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_token_reuse_prevention(self):
        _, token, _ = create_client_access_data(self.tenant, self.customer)
        url = reverse("clients_access_accept")

        # First use
        response1 = self.client.post(url, {"token": token}, format="json")
        assert response1.status_code == status.HTTP_200_OK

        # Second use (within grace period) - Should be allowed (Idempotent)
        response2 = self.client.post(url, {"token": token}, format="json")
        assert response2.status_code == status.HTTP_200_OK

        # Third use (after grace period) - Should be blocked
        from datetime import timedelta

        future = timezone.now() + timedelta(seconds=20)
        with patch("django.utils.timezone.now", return_value=future):
            response3 = self.client.post(url, {"token": token}, format="json")
            assert response3.status_code == status.HTTP_400_BAD_REQUEST
            assert (
                "utilizado" in str(response3.data).lower()
                or "inválido" in str(response3.data).lower()
            )

    def test_request_access_link_integration(self):
        """
        Testa se a view de solicitação de link pública (core.views.PublicClientAccessLinkView)
        gera o link corretamente e o passa para o serviço de envio de email.
        """
        url = reverse("public_clients_access_link")
        data = {
            "email": self.customer.email,
            "tenant_slug": self.tenant.slug,
            "captcha_token": "dev-bypass",  # Assuming dev env allows this or we mock it
        }

        # Mocking captcha enforcement if needed, but let's try with dev-bypass first
        with patch("core.views.send_customer_pwa_invite") as mock_send, patch(
            "core.views.enforce_captcha_or_raise"
        ) as mock_captcha:

            response = self.client.post(url, data, format="json")

            assert response.status_code == status.HTTP_200_OK
            assert mock_send.called

            # Verify call args
            args, kwargs = mock_send.call_args
            assert kwargs["tenant"] == self.tenant
            assert kwargs["customer"] == self.customer
            assert "link" in kwargs
            link = kwargs["link"]
            assert link is not None
            assert "token=" in link
            assert f"tenant={self.tenant.slug}" in link
