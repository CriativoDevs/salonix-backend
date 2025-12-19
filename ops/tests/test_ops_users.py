import pytest
from django.urls import reverse
from rest_framework import status
from users.models import CustomUser


@pytest.mark.django_db
class TestOpsUsersEndpoints:
    def test_list_ops_users(
        self,
        api_client,
        ops_user_factory,
        ops_authenticate,
    ):
        admin = ops_user_factory(
            CustomUser.OpsRoles.OPS_ADMIN, "admin_users@example.com"
        )
        support = ops_user_factory(
            CustomUser.OpsRoles.OPS_SUPPORT, "support_users@example.com"
        )
        # Regular user (should not be listed)
        CustomUser.objects.create_user(
            username="regular", email="regular@example.com", password="password"
        )

        access = ops_authenticate(admin.email)
        response = api_client.get(
            reverse("ops-users-list"),
            HTTP_AUTHORIZATION=f"Bearer {access}",
        )
        assert response.status_code == status.HTTP_200_OK

        results = (
            response.data.get("results")
            if isinstance(response.data, dict)
            else response.data
        )
        emails = [u["email"] for u in results]

        assert admin.email in emails
        assert support.email in emails
        assert "regular@example.com" not in emails

    def test_create_ops_user_as_admin(
        self, api_client, ops_user_factory, ops_authenticate
    ):
        admin = ops_user_factory(CustomUser.OpsRoles.OPS_ADMIN, "admin@ops.com")
        access = ops_authenticate(admin.email)

        payload = {
            "username": "new_support",
            "email": "new_support@ops.com",
            "password": "strong_password_123",
            "ops_role": CustomUser.OpsRoles.OPS_SUPPORT,
            "is_active": True,
        }

        response = api_client.post(
            reverse("ops-users-list"),
            data=payload,
            HTTP_AUTHORIZATION=f"Bearer {access}",
        )

        assert response.status_code == status.HTTP_201_CREATED
        assert response.data["email"] == payload["email"]
        assert response.data["ops_role"] == payload["ops_role"]
        assert "password" not in response.data

        # Verify DB
        user = CustomUser.objects.get(email=payload["email"])
        assert user.check_password(payload["password"])
        assert user.is_staff is True
        assert user.is_ops_user is True

    def test_create_ops_user_as_support_forbidden(
        self, api_client, ops_user_factory, ops_authenticate
    ):
        support = ops_user_factory(CustomUser.OpsRoles.OPS_SUPPORT, "support@ops.com")
        access = ops_authenticate(support.email)

        payload = {
            "username": "hacker_admin",
            "email": "hacker@ops.com",
            "password": "password",
            "ops_role": CustomUser.OpsRoles.OPS_ADMIN,
        }

        response = api_client.post(
            reverse("ops-users-list"),
            data=payload,
            HTTP_AUTHORIZATION=f"Bearer {access}",
        )

        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_update_ops_user(self, api_client, ops_user_factory, ops_authenticate):
        admin = ops_user_factory(CustomUser.OpsRoles.OPS_ADMIN, "admin@ops.com")
        target_user = ops_user_factory(
            CustomUser.OpsRoles.OPS_SUPPORT, "target@ops.com"
        )

        access = ops_authenticate(admin.email)

        payload = {
            "ops_role": CustomUser.OpsRoles.OPS_ADMIN,
            "is_active": False,
        }

        response = api_client.patch(
            reverse("ops-users-detail", kwargs={"pk": target_user.pk}),
            data=payload,
            HTTP_AUTHORIZATION=f"Bearer {access}",
        )

        assert response.status_code == status.HTTP_200_OK
        target_user.refresh_from_db()
        assert target_user.ops_role == CustomUser.OpsRoles.OPS_ADMIN
        assert target_user.is_active is False

    def test_create_duplicate_email(
        self, api_client, ops_user_factory, ops_authenticate
    ):
        admin = ops_user_factory(CustomUser.OpsRoles.OPS_ADMIN, "admin@ops.com")
        existing = ops_user_factory(CustomUser.OpsRoles.OPS_SUPPORT, "existing@ops.com")

        access = ops_authenticate(admin.email)

        payload = {
            "username": "duplicate",
            "email": "EXISTING@ops.com",  # Case insensitive check
            "password": "password",
            "ops_role": CustomUser.OpsRoles.OPS_SUPPORT,
        }

        response = api_client.post(
            reverse("ops-users-list"),
            data=payload,
            HTTP_AUTHORIZATION=f"Bearer {access}",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        # Check for error details in custom format
        error_details = response.data.get("error", {}).get("details", {})
        assert "email" in error_details
        assert error_details["email"][0] == "Este email já está em uso."
