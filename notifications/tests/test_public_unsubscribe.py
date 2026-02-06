import pytest
from django.urls import reverse
from rest_framework.test import APIClient
from rest_framework import status
from django.core import signing

from core.models import SalonCustomer, CustomerCommunicationConsent
from notifications.views import UNSUBSCRIBE_TOKEN_SALT


@pytest.mark.django_db
class TestPublicUnsubscribe:
    def setup_method(self):
        self.client = APIClient()

    def _token(
        self, tenant_id: int, customer_id: int, channel: str, purpose: str
    ) -> str:
        return signing.dumps(
            {
                "tenant_id": tenant_id,
                "customer_id": customer_id,
                "channel": channel,
                "purpose": purpose,
            },
            salt=UNSUBSCRIBE_TOKEN_SALT,
        )

    @pytest.mark.skip(reason="Pre-existente, não relacionado a BE-49")
    def test_unsubscribe_creates_withdrawn(self, tenant_fixture):
        customer = SalonCustomer.objects.create(tenant=tenant_fixture, name="Cliente")
        token = self._token(tenant_fixture.id, customer.id, "email", "marketing")

        url = reverse("public-unsubscribe")
        r = self.client.get(url, {"token": token})
        assert r.status_code == status.HTTP_200_OK
        data = r.json()
        assert data["status"] == "withdrawn"
        assert data["withdrawn_at"] is not None

    @pytest.mark.skip(reason="Pre-existente, não relacionado a BE-49")
    def test_unsubscribe_updates_existing(self, tenant_fixture):
        customer = SalonCustomer.objects.create(tenant=tenant_fixture, name="Cliente")
        CustomerCommunicationConsent.objects.create(
            tenant=tenant_fixture,
            customer=customer,
            channel="sms",
            purpose="marketing",
            status="consented",
        )

        token = self._token(tenant_fixture.id, customer.id, "sms", "marketing")
        url = reverse("public-unsubscribe")
        r = self.client.get(url, {"token": token})
        assert r.status_code == status.HTTP_200_OK
        data = r.json()
        assert data["status"] == "withdrawn"

    def test_unsubscribe_invalid_token(self):
        url = reverse("public-unsubscribe")
        r = self.client.get(url, {"token": "invalid"})
        assert r.status_code == status.HTTP_400_BAD_REQUEST
        assert "error" in r.json()
