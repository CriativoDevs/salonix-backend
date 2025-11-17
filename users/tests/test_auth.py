import pytest
from django.core.cache import cache
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
        self.me_profile_url = reverse("me_profile")
        # Evita interferência de throttling entre testes consecutivos
        cache.clear()

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
        # Com branding atualizado, verificar app_name (fallback para name)
        assert tenant["branding"]["app_name"] == "lucas"

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
        assert response.data["user"]["username"] == "lucas"
        assert response.data["user"]["email"] == "lucas@example.com"

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

    def test_me_profile_returns_user_payload(self):
        user = User.objects.create_user(
            username="profileuser",
            email="profile@example.com",
            password="testpass123",
        )
        self.client.force_authenticate(user=user)

        response = self.client.get(self.me_profile_url)

        assert response.status_code == status.HTTP_200_OK
        assert response.data["username"] == "profileuser"
        assert response.data["email"] == "profile@example.com"
        assert "theme_preference" in response.data
        assert response.data["theme_preference"] == "system"  # default value

    def test_update_theme_preference_success(self):
        user = User.objects.create_user(
            username="themeuser",
            email="theme@example.com",
            password="testpass123",
        )
        self.client.force_authenticate(user=user)

        # Test updating to light theme
        response = self.client.patch(self.me_profile_url, {"theme_preference": "light"})
        assert response.status_code == status.HTTP_200_OK
        assert response.data["theme_preference"] == "light"

        # Test updating to dark theme
        response = self.client.patch(self.me_profile_url, {"theme_preference": "dark"})
        assert response.status_code == status.HTTP_200_OK
        assert response.data["theme_preference"] == "dark"

        # Test updating to system theme
        response = self.client.patch(
            self.me_profile_url, {"theme_preference": "system"}
        )
        assert response.status_code == status.HTTP_200_OK
        assert response.data["theme_preference"] == "system"

    def test_update_theme_preference_invalid_value(self):
        user = User.objects.create_user(
            username="invalidthemeuser",
            email="invalidtheme@example.com",
            password="testpass123",
        )
        self.client.force_authenticate(user=user)

        response = self.client.patch(
            self.me_profile_url, {"theme_preference": "invalid"}
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "theme_preference deve ser um dos valores" in response.data["detail"]

    def test_update_theme_preference_missing_field(self):
        user = User.objects.create_user(
            username="missingthemeuser",
            email="missingtheme@example.com",
            password="testpass123",
        )
        self.client.force_authenticate(user=user)

        response = self.client.patch(self.me_profile_url, {})
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "theme_preference é obrigatório" in response.data["detail"]

    def test_update_theme_preference_requires_authentication(self):
        response = self.client.patch(self.me_profile_url, {"theme_preference": "light"})
        assert response.status_code == status.HTTP_401_UNAUTHORIZED
