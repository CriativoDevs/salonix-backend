import csv
import io
from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone
from django.utils.text import slugify
from rest_framework import status
from rest_framework.test import APIClient

from notifications.models import NotificationLog
from users.models import CustomUser, Tenant, UserFeatureFlags


@pytest.fixture
def api_client():
    return APIClient()


def _create_ops_user(role: str, email: str) -> CustomUser:
    user = CustomUser(
        username=email.split("@")[0],
        email=email,
        ops_role=role,
        is_active=True,
    )
    user._tenant_explicitly_none = True
    user.set_password("OpsPass123!")
    user.save()
    return user


def _authenticate_ops(client: APIClient, email: str, password: str = "OpsPass123!") -> str:
    response = client.post(
        reverse("ops_auth_login"),
        {"email": email, "password": password},
        format="json",
    )
    assert response.status_code == status.HTTP_200_OK
    return response.data["access"]


def _create_tenant_with_owner(
    name: str,
    plan_tier: str = Tenant.PLAN_PRO,
    is_active: bool = True,
    sms_enabled: bool = False,
    whatsapp_enabled: bool = False,
    addons: list[str] | None = None,
) -> tuple[Tenant, CustomUser]:
    tenant = Tenant.objects.create(
        name=name,
        slug=slugify(name),
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
    owner.save(update_fields=["last_login"])

    UserFeatureFlags.objects.update_or_create(
        user=owner,
        defaults={
            "trial_until": timezone.now() + timedelta(days=14),
            "pro_status": UserFeatureFlags.STATUS_TRIALING,
        },
    )

    return tenant, owner


@pytest.mark.django_db
class TestOpsTenantsEndpoints:
    def test_ops_admin_can_list_tenants(self, api_client):
        admin = _create_ops_user(CustomUser.OpsRoles.OPS_ADMIN, "admin_ops@example.com")
        tenant, owner = _create_tenant_with_owner("Salon Alpha", sms_enabled=True)

        NotificationLog.objects.create(
            tenant=tenant,
            user=owner,
            channel="sms",
            notification_type="system",
            title="Teste",
            message="Mensagem",
            status="sent",
        )
        NotificationLog.objects.create(
            tenant=tenant,
            user=owner,
            channel="whatsapp",
            notification_type="system",
            title="Teste",
            message="Mensagem",
            status="delivered",
        )

        access = _authenticate_ops(api_client, admin.email)
        response = api_client.get(
            reverse("ops-tenants-list"),
            HTTP_AUTHORIZATION=f"Bearer {access}",
        )
        assert response.status_code == status.HTTP_200_OK
        assert "results" in response.data

        tenant_data = next(
            item for item in response.data["results"] if item["id"] == tenant.id
        )

        assert tenant_data["plan_tier"] == Tenant.PLAN_PRO
        assert tenant_data["user_counts"]["total"] == 1
        assert tenant_data["notification_consumption"]["sms_total"] == 1
        assert tenant_data["notification_consumption"]["whatsapp_total"] == 1
        assert tenant_data["history"]["trial_status"] == UserFeatureFlags.STATUS_TRIALING
        assert tenant_data["owner"]["email"].endswith("@owner.test")

    def test_filters_and_ordering(self, api_client):
        admin = _create_ops_user(CustomUser.OpsRoles.OPS_ADMIN, "filters_ops@example.com")
        tenant_pro, _ = _create_tenant_with_owner("Salon Pro", plan_tier=Tenant.PLAN_PRO)
        tenant_basic, _ = _create_tenant_with_owner(
            "Salon Basic",
            plan_tier=Tenant.PLAN_BASIC,
            is_active=False,
        )
        # Adiciona usuário extra para ordenar por contagem
        CustomUser.objects.create_user(
            username="extra_user",
            email="extra@user.test",
            password="Extra123!",
            tenant=tenant_pro,
        )

        access = _authenticate_ops(api_client, admin.email)
        response = api_client.get(
            reverse("ops-tenants-list"),
            {"plan_tier": Tenant.PLAN_BASIC, "is_active": "false"},
            HTTP_AUTHORIZATION=f"Bearer {access}",
        )
        assert response.status_code == status.HTTP_200_OK
        ids = [item["id"] for item in response.data["results"]]
        assert tenant_basic.id in ids
        assert tenant_pro.id not in ids

        response = api_client.get(
            reverse("ops-tenants-list"),
            {"ordering": "-users_total"},
            HTTP_AUTHORIZATION=f"Bearer {access}",
        )
        assert response.status_code == status.HTTP_200_OK
        first = response.data["results"][0]
        assert first["id"] == tenant_pro.id

    def test_export_csv_sets_headers(self, api_client):
        admin = _create_ops_user(CustomUser.OpsRoles.OPS_ADMIN, "export_ops@example.com")
        tenant, _ = _create_tenant_with_owner("Salon Export")
        access = _authenticate_ops(api_client, admin.email)

        response = api_client.get(
            reverse("ops-tenants-export"),
            HTTP_AUTHORIZATION=f"Bearer {access}",
        )
        assert response.status_code == status.HTTP_200_OK
        assert response["Content-Type"] == "text/csv"
        assert "attachment" in response["Content-Disposition"]

        content = response.content.decode()
        csv_reader = csv.reader(io.StringIO(content))
        rows = list(csv_reader)
        assert any(str(tenant.id) in row for row in rows)

    def test_plan_change_requires_force_when_conflicts(self, api_client):
        admin = _create_ops_user(CustomUser.OpsRoles.OPS_ADMIN, "plan_ops@example.com")
        tenant, _ = _create_tenant_with_owner(
            "Salon Force",
            plan_tier=Tenant.PLAN_PRO,
            sms_enabled=True,
            whatsapp_enabled=True,
            addons=["rn_admin"],
        )

        access = _authenticate_ops(api_client, admin.email)
        url = reverse("ops-tenants-update-plan", kwargs={"pk": tenant.id})

        response = api_client.patch(
            url,
            {"plan_tier": Tenant.PLAN_STANDARD},
            format="json",
            HTTP_AUTHORIZATION=f"Bearer {access}",
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "conflicts" in response.data["error"]["details"]

        response = api_client.patch(
            url,
            {"plan_tier": Tenant.PLAN_STANDARD, "force": True},
            format="json",
            HTTP_AUTHORIZATION=f"Bearer {access}",
        )
        assert response.status_code == status.HTTP_200_OK
        tenant.refresh_from_db()
        assert tenant.plan_tier == Tenant.PLAN_STANDARD
        assert tenant.sms_enabled is False
        assert tenant.whatsapp_enabled is False
        assert "rn_admin" not in (tenant.addons_enabled or [])

    def test_block_and_unblock(self, api_client):
        admin = _create_ops_user(CustomUser.OpsRoles.OPS_ADMIN, "block_ops@example.com")
        tenant, _ = _create_tenant_with_owner("Salon Lock")
        access = _authenticate_ops(api_client, admin.email)

        block_resp = api_client.post(
            reverse("ops-tenants-block-tenant", kwargs={"pk": tenant.id}),
            HTTP_AUTHORIZATION=f"Bearer {access}",
        )
        assert block_resp.status_code == status.HTTP_200_OK
        tenant.refresh_from_db()
        assert tenant.is_active is False

        unblock_resp = api_client.post(
            reverse("ops-tenants-unblock-tenant", kwargs={"pk": tenant.id}),
            HTTP_AUTHORIZATION=f"Bearer {access}",
        )
        assert unblock_resp.status_code == status.HTTP_200_OK
        tenant.refresh_from_db()
        assert tenant.is_active is True

    def test_support_cannot_modify(self, api_client):
        support = _create_ops_user(CustomUser.OpsRoles.OPS_SUPPORT, "support_ops@example.com")
        tenant, _ = _create_tenant_with_owner("Salon Support")
        access = _authenticate_ops(api_client, support.email)

        response = api_client.post(
            reverse("ops-tenants-block-tenant", kwargs={"pk": tenant.id}),
            HTTP_AUTHORIZATION=f"Bearer {access}",
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert response.data["error"]["code"] == "E004"

    def test_reset_owner_updates_credentials(self, api_client):
        admin = _create_ops_user(CustomUser.OpsRoles.OPS_ADMIN, "owner_ops@example.com")
        tenant, owner = _create_tenant_with_owner("Salon Reset")
        access = _authenticate_ops(api_client, admin.email)

        response = api_client.post(
            reverse("ops-tenants-reset-owner", kwargs={"pk": tenant.id}),
            {"email": "new.owner@example.com", "username": "newowner"},
            format="json",
            HTTP_AUTHORIZATION=f"Bearer {access}",
        )
        assert response.status_code == status.HTTP_200_OK
        data = response.data
        assert data["email"] == "new.owner@example.com"
        assert "temporary_password" in data

        owner.refresh_from_db()
        assert owner.email == "new.owner@example.com"
        assert owner.username == "newowner"
        temp_password = data["temporary_password"]

        token_response = api_client.post(
            reverse("token_obtain_pair"),
            {"email": owner.email, "password": temp_password},
            format="json",
        )
        assert token_response.status_code == status.HTTP_200_OK
