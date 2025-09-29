import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

User = get_user_model()


@pytest.mark.django_db
class TestAuthEndpoints:

    def setup_method(self):
        self.client = APIClient()
        self.register_url = reverse("register")
        self.token_url = reverse("token_obtain_pair")
        self.me_tenant_url = reverse("me_tenant")

    def test_successful_registration(self):
        payload = {
            "username": "lucas",
            "email": "lucas@salonix.com",
            "password": "strongpassword123",
        }
        response = self.client.post(self.register_url, data=payload)
        assert response.status_code == status.HTTP_201_CREATED
        assert "id" in response.data
        assert "tenant" in response.data
        tenant = response.data["tenant"]
        assert tenant["slug"] == "lucas"
        assert tenant["plan"]["tier"] == "basic"
        assert tenant["branding"]["primary_color"] == "#3B82F6"

    def test_registration_missing_fields(self):
        response = self.client.post(self.register_url, data={"email": "x@x.com"})
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        # Com novo sistema de erros, a estrutura mudou
        assert "error" in response.data
        assert "username" in response.data["error"]["details"]
        assert "password" in response.data["error"]["details"]

    def test_successful_login(self):
        User.objects.create_user(
            username="lucas",
            email="lucas@example.com",
            password="testpass123",
        )
        payload = {"email": "lucas@example.com", "password": "testpass123"}
        response = self.client.post(self.token_url, data=payload)
        assert response.status_code == status.HTTP_200_OK
        assert "access" in response.data
        assert "refresh" in response.data
        assert response.data["tenant"]["slug"] == "test-default"

        refresh = RefreshToken(response.data["refresh"])
        access = refresh.access_token
        assert refresh.get("scope") == "tenant"
        assert access.get("scope") == "tenant"
        assert refresh.get("tenant_slug") == "test-default"
        assert access.get("tenant_slug") == "test-default"

    def test_registration_generates_unique_slug(self):
        first_payload = {
            "username": "ana",
            "email": "ana@example.com",
            "password": "strongpass123",
            "salon_name": "Studio Glam",
        }
        second_payload = {
            "username": "carla",
            "email": "carla@example.com",
            "password": "anotherpass123",
            "salon_name": "Studio Glam",
        }

        first_response = self.client.post(self.register_url, data=first_payload)
        assert first_response.status_code == status.HTTP_201_CREATED
        assert first_response.data["tenant"]["slug"] == "studio-glam"

        second_response = self.client.post(self.register_url, data=second_payload)
        assert second_response.status_code == status.HTTP_201_CREATED
        assert second_response.data["tenant"]["slug"].startswith("studio-glam")
        assert second_response.data["tenant"]["slug"] != "studio-glam"

    def test_registration_duplicate_email_returns_400(self):
        User.objects.create_user(
            username="existing",
            email="duplicate@example.com",
            password="StrongPass123",
        )

        payload = {
            "username": "newuser",
            "email": "duplicate@example.com",
            "password": "AnotherPass123",
        }

        response = self.client.post(self.register_url, data=payload)

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        error = response.data.get("error", {})
        assert "details" in error
        assert "email" in error["details"]

    def test_registration_duplicate_email_case_insensitive(self):
        User.objects.create_user(
            username="existing",
            email="duplicate@example.com",
            password="StrongPass123",
        )

        payload = {
            "username": "anotheruser",
            "email": "Duplicate@Example.com",
            "password": "AnotherPass123",
        }

        response = self.client.post(self.register_url, data=payload)

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        error = response.data.get("error", {})
        assert "details" in error
        assert "email" in error["details"]

    def test_ops_user_blocked_from_tenant_login(self):
        user = User(
            username="opsuser",
            email="ops@example.com",
            ops_role=User.OpsRoles.OPS_ADMIN,
            is_active=True,
        )
        user._tenant_explicitly_none = True
        user.set_password("StrongPass!123")
        user.save()

        payload = {"email": "ops@example.com", "password": "StrongPass!123"}
        response = self.client.post(self.token_url, data=payload)
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_login_with_wrong_password(self):
        User.objects.create_user(
            username="lucas",
            email="lucas@example.com",
            password="testpass123",
        )
        payload = {"email": "lucas@example.com", "password": "wrongpassword"}
        response = self.client.post(self.token_url, data=payload)
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_login_with_nonexistent_user(self):
        payload = {"email": "doesnotexist@example.com", "password": "irrelevant"}
        response = self.client.post(self.token_url, data=payload)
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_me_tenant_returns_payload(self, tenant_fixture):
        user = User.objects.create_user(
            username="owner",
            email="owner@example.com",
            password="StrongPass123",
            tenant=tenant_fixture,
        )

        self.client.force_authenticate(user=user)
        response = self.client.get(self.me_tenant_url)

        assert response.status_code == status.HTTP_200_OK
        assert response.data["id"] == tenant_fixture.id
        assert response.data["slug"] == tenant_fixture.slug
        assert response.data["plan"]["tier"] == tenant_fixture.plan_tier

    def test_me_tenant_without_tenant_returns_404(self):
        user = User(
            username="opsuser",
            email="ops@example.com",
            ops_role=User.OpsRoles.OPS_ADMIN,
            is_active=True,
        )
        user._tenant_explicitly_none = True
        user.set_password("StrongPass!123")
        user.save()

        self.client.force_authenticate(user=user)
        response = self.client.get(self.me_tenant_url)

        assert response.status_code == status.HTTP_404_NOT_FOUND
        assert "error" in response.data
        assert "error_id" in response.data["error"]

    def test_me_tenant_requires_authentication(self):
        response = self.client.get(self.me_tenant_url)
        assert response.status_code == status.HTTP_401_UNAUTHORIZED
