import pytest
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient
from django.core import signing
from users.models import Tenant
from core.models import SalonCustomer

@pytest.mark.django_db
class TestClientLoginFlow:
    def setup_method(self):
        self.tenant = Tenant.objects.create(
            name="Test Salon",
            slug="test-salon",
            plan_tier=Tenant.PLAN_STANDARD,
            pwa_client_enabled=True,
        )
        self.customer = SalonCustomer.objects.create(
            tenant=self.tenant,
            name="Test Client",
            email="client@test.com",
            is_active=True,
        )
        self.client = APIClient()

    def test_set_and_check_password_model(self):
        self.customer.set_password("securepass123")
        self.customer.save()
        
        self.customer.refresh_from_db()
        assert self.customer.password is not None
        assert self.customer.check_password("securepass123")
        assert not self.customer.check_password("wrongpass")

    def test_login_success(self):
        self.customer.set_password("securepass123")
        self.customer.save()

        url = reverse("clients_login")
        data = {
            "email": "client@test.com",
            "password": "securepass123",
            "tenant_slug": "test-salon"
        }
        response = self.client.post(url, data, format="json")

        assert response.status_code == status.HTTP_200_OK
        assert "client_session" in response.cookies
        assert response.data["session"] == "created"

    def test_login_invalid_password(self):
        self.customer.set_password("securepass123")
        self.customer.save()

        url = reverse("clients_login")
        data = {
            "email": "client@test.com",
            "password": "wrongpass",
            "tenant_slug": "test-salon"
        }
        response = self.client.post(url, data, format="json")

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "Credenciais inválidas" in str(response.data)

    def test_login_no_password_set(self):
        # Password is None by default
        url = reverse("clients_login")
        data = {
            "email": "client@test.com",
            "password": "any",
            "tenant_slug": "test-salon"
        }
        response = self.client.post(url, data, format="json")

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "não possui senha definida" in str(response.data)

    def test_set_password_flow(self):
        # 1. Simulate authenticated session via cookie
        session_payload = {
            "tenant_id": self.tenant.id,
            "customer_id": self.customer.id,
        }
        token = signing.dumps(session_payload, salt="CLIENT_PWA_SESSION_SALT")
        self.client.cookies["client_session"] = token

        # 2. Call set-password
        url = reverse("clients_set_password")
        data = {"password": "newpassword123"}
        response = self.client.post(url, data, format="json")

        assert response.status_code == status.HTTP_200_OK
        
        # 3. Verify in DB
        self.customer.refresh_from_db()
        assert self.customer.check_password("newpassword123")

    def test_set_password_unauthenticated(self):
        url = reverse("clients_set_password")
        data = {"password": "newpassword123"}
        response = self.client.post(url, data, format="json")

        assert response.status_code == status.HTTP_400_BAD_REQUEST # ValidationError "Sessão ausente"
