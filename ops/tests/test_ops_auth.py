import pytest
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken, AccessToken

from users.models import CustomUser


@pytest.mark.django_db
class TestOpsAuth:
    def setup_method(self):
        self.client = APIClient()
        self.login_url = reverse("ops_auth_login")
        self.refresh_url = reverse("ops_auth_refresh")
        self.tenant_login_url = reverse("token_obtain_pair")
        self.me_features_url = reverse("me_feature_flags")

    def _create_ops_user(self, role: str) -> CustomUser:
        user = CustomUser(
            username=f"{role}_user",
            email=f"{role}@example.com",
            ops_role=role,
            is_active=True,
        )
        user._tenant_explicitly_none = True
        user.set_password("StrongPass!123")
        user.save()
        return user

    def test_ops_login_success_returns_scoped_tokens(self):
        user = self._create_ops_user(CustomUser.OpsRoles.OPS_ADMIN)

        response = self.client.post(
            self.login_url,
            {"email": user.email, "password": "StrongPass!123"},
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK
        assert set(response.data.keys()) >= {"access", "refresh", "ops_role", "user_id"}
        assert response.data["ops_role"] == CustomUser.OpsRoles.OPS_ADMIN

        refresh = RefreshToken(response.data["refresh"])
        access = AccessToken(response.data["access"])
        assert refresh.get("scope") == CustomUser.OpsRoles.OPS_ADMIN
        assert access.get("scope") == CustomUser.OpsRoles.OPS_ADMIN
        assert refresh.get("tenant_slug") is None
        assert access.get("tenant_slug") is None
        assert refresh.get("user_id") == str(user.id)

    def test_ops_login_rejects_invalid_credentials(self):
        user = self._create_ops_user(CustomUser.OpsRoles.OPS_SUPPORT)

        response = self.client.post(
            self.login_url,
            {"email": user.email, "password": "wrong"},
            format="json",
        )

        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_ops_login_rejects_tenant_user(self):
        CustomUser.objects.create_user(
            username="tenantuser",
            email="tenant@example.com",
            password="TenantPass123",
        )

        response = self.client.post(
            self.login_url,
            {"email": "tenant@example.com", "password": "TenantPass123"},
            format="json",
        )

        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_ops_refresh_requires_ops_scope(self):
        user = self._create_ops_user(CustomUser.OpsRoles.OPS_SUPPORT)
        login = self.client.post(
            self.login_url,
            {"email": user.email, "password": "StrongPass!123"},
            format="json",
        )
        assert login.status_code == status.HTTP_200_OK
        refresh_token = login.data["refresh"]

        response = self.client.post(
            self.refresh_url,
            {"refresh": refresh_token},
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK
        assert "access" in response.data
        assert response.data["ops_role"] == CustomUser.OpsRoles.OPS_SUPPORT
        access = AccessToken(response.data["access"])
        assert access.get("scope") == CustomUser.OpsRoles.OPS_SUPPORT

    def test_scope_middleware_blocks_ops_on_tenant_routes(self):
        user = self._create_ops_user(CustomUser.OpsRoles.OPS_ADMIN)
        login = self.client.post(
            self.login_url,
            {"email": user.email, "password": "StrongPass!123"},
            format="json",
        )
        assert login.status_code == status.HTTP_200_OK
        access_token = login.data["access"]

        response = self.client.get(
            self.me_features_url,
            HTTP_AUTHORIZATION=f"Bearer {access_token}",
        )

        assert response.status_code == status.HTTP_403_FORBIDDEN
        payload = response.json()
        assert payload["error"]["code"] == "E004"

    def test_scope_middleware_blocks_tenant_on_ops_routes(self):
        tenant_user = CustomUser.objects.create_user(
            username="tenant_middleware",
            email="tenant-middleware@example.com",
            password="TenantPass123",
        )

        tenant_login = self.client.post(
            self.tenant_login_url,
            {"email": tenant_user.email, "password": "TenantPass123"},
            format="json",
        )
        assert tenant_login.status_code == status.HTTP_200_OK
        tenant_access = tenant_login.data["access"]

        response = self.client.post(
            self.refresh_url,
            {"refresh": "dummy"},
            format="json",
            HTTP_AUTHORIZATION=f"Bearer {tenant_access}",
        )

        assert response.status_code == status.HTTP_403_FORBIDDEN
        payload = response.json()
        assert payload["error"]["code"] == "E004"
