import pytest
from datetime import timedelta
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from users.models import CustomUser, Tenant, UserFeatureFlags


@pytest.fixture
def api_client() -> APIClient:
    return APIClient()


@pytest.fixture
def ops_user_factory(db):
    created_users = []

    def factory(role: str, email: str, password: str = "OpsPass123!") -> CustomUser:
        user = CustomUser(
            username=email.split("@")[0],
            email=email,
            ops_role=role,
            is_active=True,
        )
        user._tenant_explicitly_none = True  # evitar associação automática nos testes
        user.set_password(password)
        user.save()
        created_users.append(user)
        return user

    yield factory

    for user in created_users:
        user.refresh_from_db()


@pytest.fixture
def ops_authenticate(api_client):
    def authenticate(email: str, password: str = "OpsPass123!") -> str:
        response = api_client.post(
            reverse("ops_auth_login"),
            {"email": email, "password": password},
            format="json",
        )
        assert response.status_code == status.HTTP_200_OK
        return response.data["access"]

    return authenticate


@pytest.fixture
def tenant_with_owner_factory(db):
    def factory(
        name: str,
        plan_tier: str = Tenant.PLAN_PRO,
        is_active: bool = True,
        sms_enabled: bool = False,
        whatsapp_enabled: bool = False,
        addons: list[str] | None = None,
    ):
        tenant = Tenant.objects.create(
            name=name,
            slug=name.lower().replace(" ", "-"),
            plan_tier=plan_tier,
            is_active=is_active,
            sms_enabled=sms_enabled,
            whatsapp_enabled=whatsapp_enabled,
            addons_enabled=addons or [],
        )

        owner = CustomUser.objects.create_user(
            username=f"{tenant.slug}_owner",
            email=f"{tenant.slug}@owner.test",
            password="OwnerPass123!",
            tenant=tenant,
        )
        owner.last_login = timezone.now() - timedelta(days=1)
        owner.phone_number = "+351999000111"
        owner.save(update_fields=["last_login", "phone_number"])

        UserFeatureFlags.objects.update_or_create(
            user=owner,
            defaults={
                "trial_until": timezone.now() + timedelta(days=14),
                "pro_status": UserFeatureFlags.STATUS_TRIALING,
            },
        )

        return tenant, owner

    return factory
