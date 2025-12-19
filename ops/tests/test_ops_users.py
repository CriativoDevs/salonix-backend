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
