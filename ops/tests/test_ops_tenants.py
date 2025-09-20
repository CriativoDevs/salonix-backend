import csv
import io

import pytest
from django.urls import reverse
from rest_framework import status

from notifications.models import NotificationLog
from users.models import CustomUser, Tenant


@pytest.mark.django_db
class TestOpsTenantsEndpoints:
    def test_ops_admin_can_list_tenants(
        self,
        api_client,
        ops_user_factory,
        ops_authenticate,
        tenant_with_owner_factory,
    ):
        admin = ops_user_factory(CustomUser.OpsRoles.OPS_ADMIN, "admin_ops@example.com")
        tenant, owner = tenant_with_owner_factory("Salon Alpha", sms_enabled=True)

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

        access = ops_authenticate(admin.email)
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
        assert tenant_data["owner"]["email"].endswith("@owner.test")

    def test_filters_and_ordering(
        self,
        api_client,
        ops_user_factory,
        ops_authenticate,
        tenant_with_owner_factory,
    ):
        admin = ops_user_factory(CustomUser.OpsRoles.OPS_ADMIN, "filters_ops@example.com")
        tenant_pro, _ = tenant_with_owner_factory("Salon Pro", plan_tier=Tenant.PLAN_PRO)
        tenant_basic, _ = tenant_with_owner_factory(
            "Salon Basic",
            plan_tier=Tenant.PLAN_BASIC,
            is_active=False,
        )
        CustomUser.objects.create_user(
            username="extra_user",
            email="extra@user.test",
            password="Extra123!",
            tenant=tenant_pro,
        )

        access = ops_authenticate(admin.email)
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

    def test_export_csv_sets_headers(
        self,
        api_client,
        ops_user_factory,
        ops_authenticate,
        tenant_with_owner_factory,
    ):
        admin = ops_user_factory(CustomUser.OpsRoles.OPS_ADMIN, "export_ops@example.com")
        tenant, _ = tenant_with_owner_factory("Salon Export")
        access = ops_authenticate(admin.email)

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

    def test_plan_change_requires_force_when_conflicts(
        self,
        api_client,
        ops_user_factory,
        ops_authenticate,
        tenant_with_owner_factory,
    ):
        admin = ops_user_factory(CustomUser.OpsRoles.OPS_ADMIN, "plan_ops@example.com")
        tenant, _ = tenant_with_owner_factory(
            "Salon Force",
            plan_tier=Tenant.PLAN_PRO,
            sms_enabled=True,
            whatsapp_enabled=True,
            addons=["rn_admin"],
        )

        access = ops_authenticate(admin.email)
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

    def test_block_and_unblock(
        self,
        api_client,
        ops_user_factory,
        ops_authenticate,
        tenant_with_owner_factory,
    ):
        admin = ops_user_factory(CustomUser.OpsRoles.OPS_ADMIN, "block_ops@example.com")
        tenant, _ = tenant_with_owner_factory("Salon Lock")
        access = ops_authenticate(admin.email)

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

    def test_support_cannot_modify(
        self,
        api_client,
        ops_user_factory,
        ops_authenticate,
        tenant_with_owner_factory,
    ):
        support = ops_user_factory(CustomUser.OpsRoles.OPS_SUPPORT, "support_ops@example.com")
        tenant, _ = tenant_with_owner_factory("Salon Support")
        access = ops_authenticate(support.email)

        response = api_client.post(
            reverse("ops-tenants-block-tenant", kwargs={"pk": tenant.id}),
            HTTP_AUTHORIZATION=f"Bearer {access}",
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert response.data["error"]["code"] == "E004"

    def test_reset_owner_updates_credentials(
        self,
        api_client,
        ops_user_factory,
        ops_authenticate,
        tenant_with_owner_factory,
    ):
        admin = ops_user_factory(CustomUser.OpsRoles.OPS_ADMIN, "owner_ops@example.com")
        tenant, owner = tenant_with_owner_factory("Salon Reset")
        access = ops_authenticate(admin.email)

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
