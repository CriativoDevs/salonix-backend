import csv
import io

import pytest
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from notifications.models import NotificationLog
from ops.models import OpsSupportAuditLog
from users.models import CustomUser, Tenant, TenantStaffMember


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

        results = (
            response.data.get("results")
            if isinstance(response.data, dict)
            else response.data
        )

        tenant_data = next(item for item in results if item["id"] == tenant.id)

        assert tenant_data["plan_tier"] == Tenant.PLAN_PRO
        assert tenant_data["user_counts"]["total"] == 1
        assert tenant_data["notification_consumption"]["sms"] == 1
        assert tenant_data["notification_consumption"]["whatsapp"] == 1
        assert tenant_data["owner"]["email"].endswith("@owner.test")

    def test_filters_and_ordering(
        self,
        api_client,
        ops_user_factory,
        ops_authenticate,
        tenant_with_owner_factory,
    ):
        admin = ops_user_factory(
            CustomUser.OpsRoles.OPS_ADMIN, "filters_ops@example.com"
        )
        tenant_pro, _ = tenant_with_owner_factory(
            "Salon Pro", plan_tier=Tenant.PLAN_PRO
        )
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

        results = (
            response.data.get("results")
            if isinstance(response.data, dict)
            else response.data
        )
        ids = [item["id"] for item in results]

        assert tenant_basic.id in ids
        assert tenant_pro.id not in ids

        response = api_client.get(
            reverse("ops-tenants-list"),
            {"ordering": "-users_total"},
            HTTP_AUTHORIZATION=f"Bearer {access}",
        )
        assert response.status_code == status.HTTP_200_OK

        results_ordered = (
            response.data.get("results")
            if isinstance(response.data, dict)
            else response.data
        )
        first = results_ordered[0]
        assert first["id"] == tenant_pro.id

    def test_export_csv_sets_headers(
        self,
        api_client,
        ops_user_factory,
        ops_authenticate,
        tenant_with_owner_factory,
    ):
        admin = ops_user_factory(
            CustomUser.OpsRoles.OPS_ADMIN, "export_ops@example.com"
        )
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

        # BE-PLANS-01 (#481): todos os planos ativos suportam SMS/WhatsApp/addons;
        # a mudança de plano não gera mais conflitos nem exige force.
        response = api_client.post(
            url,
            {"plan_tier": Tenant.PLAN_BASIC},
            format="json",
            HTTP_AUTHORIZATION=f"Bearer {access}",
        )
        assert response.status_code == status.HTTP_200_OK
        tenant.refresh_from_db()
        assert tenant.plan_tier == Tenant.PLAN_BASIC
        # Features absorvidas permanecem habilitadas após a mudança de plano
        assert tenant.sms_enabled is True
        assert tenant.whatsapp_enabled is True
        assert "rn_admin" in (tenant.addons_enabled or [])

    def test_plan_downgrade_invalidates_tenant_sessions_only(
        self,
        api_client,
        ops_user_factory,
        ops_authenticate,
        tenant_with_owner_factory,
    ):
        admin = ops_user_factory(
            CustomUser.OpsRoles.OPS_ADMIN, "downgrade_ops@example.com"
        )
        tenant, owner = tenant_with_owner_factory(
            "Salon Downgrade", plan_tier=Tenant.PLAN_PRO
        )
        _, other_owner = tenant_with_owner_factory(
            "Salon Other", plan_tier=Tenant.PLAN_PRO
        )

        collaborator = CustomUser.objects.create_user(
            username="downgrade_collab",
            email="downgrade-collab@example.com",
            password="OwnerPass123!",
            tenant=tenant,
        )
        TenantStaffMember.objects.create(
            tenant=tenant,
            user=collaborator,
            role=TenantStaffMember.Role.COLLABORATOR,
            status=TenantStaffMember.Status.ACTIVE,
        )

        owner.jwt_version = 5
        owner.save(update_fields=["jwt_version"])
        collaborator.jwt_version = 3
        collaborator.save(update_fields=["jwt_version"])
        other_owner.jwt_version = 7
        other_owner.save(update_fields=["jwt_version"])

        access = ops_authenticate(admin.email)
        url = reverse("ops-tenants-update-plan", kwargs={"pk": tenant.id})
        response = api_client.post(
            url,
            {"plan_tier": Tenant.PLAN_BASIC},
            format="json",
            HTTP_AUTHORIZATION=f"Bearer {access}",
        )

        assert response.status_code == status.HTTP_200_OK
        assert response.data["is_downgrade"] is True
        assert response.data["invalidated_sessions"] == 2

        owner.refresh_from_db()
        collaborator.refresh_from_db()
        other_owner.refresh_from_db()
        assert owner.jwt_version == 6
        assert collaborator.jwt_version == 4
        assert other_owner.jwt_version == 7

        audit = OpsSupportAuditLog.objects.filter(
            action=OpsSupportAuditLog.Actions.UPDATE_PLAN,
            target_tenant=tenant,
        ).first()
        assert audit is not None
        assert audit.actor_id == admin.id
        assert audit.payload["old_plan"] == Tenant.PLAN_PRO
        assert audit.payload["new_plan"] == Tenant.PLAN_BASIC
        assert audit.payload["is_downgrade"] is True
        assert audit.payload["invalidated_sessions"] == 2
        assert audit.result["status"] == "success"
        assert audit.result["revocation_applied"] is True
        assert audit.result["invalidated_sessions"] == 2

    def test_plan_upgrade_does_not_invalidate_sessions_by_default(
        self,
        api_client,
        ops_user_factory,
        ops_authenticate,
        tenant_with_owner_factory,
    ):
        admin = ops_user_factory(
            CustomUser.OpsRoles.OPS_ADMIN, "upgrade_ops@example.com"
        )
        tenant, owner = tenant_with_owner_factory(
            "Salon Upgrade", plan_tier=Tenant.PLAN_BASIC
        )

        owner.jwt_version = 4
        owner.save(update_fields=["jwt_version"])

        access = ops_authenticate(admin.email)
        url = reverse("ops-tenants-update-plan", kwargs={"pk": tenant.id})
        # BE-PLANS-01 (#481): Pro bloqueado; upgrade de teste passa a usar Founder.
        response = api_client.post(
            url,
            {"plan_tier": Tenant.PLAN_FOUNDER},
            format="json",
            HTTP_AUTHORIZATION=f"Bearer {access}",
        )

        assert response.status_code == status.HTTP_200_OK
        assert response.data["is_downgrade"] is False
        assert response.data["invalidated_sessions"] == 0

        owner.refresh_from_db()
        assert owner.jwt_version == 4

    def test_plan_downgrade_revokes_old_access_and_refresh_tokens_immediately(
        self,
        api_client,
        ops_user_factory,
        ops_authenticate,
        tenant_with_owner_factory,
    ):
        admin = ops_user_factory(
            CustomUser.OpsRoles.OPS_ADMIN, "downgrade_revoke_ops@example.com"
        )
        tenant, owner = tenant_with_owner_factory(
            "Salon Revoke", plan_tier=Tenant.PLAN_PRO
        )

        tenant_client = APIClient()
        login_response = tenant_client.post(
            reverse("token_obtain_pair"),
            {"email": owner.email, "password": "OwnerPass123!"},
            format="json",
        )
        assert login_response.status_code == status.HTTP_200_OK
        old_access = login_response.data["access"]
        old_refresh = login_response.data["refresh"]

        # Token antigo funciona antes do downgrade
        tenant_client.credentials(HTTP_AUTHORIZATION=f"Bearer {old_access}")
        before_response = tenant_client.get(reverse("me_profile"))
        assert before_response.status_code == status.HTTP_200_OK

        access = ops_authenticate(admin.email)
        downgrade_url = reverse("ops-tenants-update-plan", kwargs={"pk": tenant.id})
        downgrade_response = api_client.post(
            downgrade_url,
            {"plan_tier": Tenant.PLAN_BASIC},
            format="json",
            HTTP_AUTHORIZATION=f"Bearer {access}",
        )
        assert downgrade_response.status_code == status.HTTP_200_OK
        assert downgrade_response.data["is_downgrade"] is True

        # Access token antigo deve falhar imediatamente
        after_access_response = tenant_client.get(reverse("me_profile"))
        assert after_access_response.status_code == status.HTTP_401_UNAUTHORIZED

        # Refresh token antigo também deve ser rejeitado
        refresh_response = tenant_client.post(
            reverse("token_refresh"),
            {"refresh": old_refresh},
            format="json",
        )
        assert refresh_response.status_code == status.HTTP_401_UNAUTHORIZED

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
        support = ops_user_factory(
            CustomUser.OpsRoles.OPS_SUPPORT, "support_ops@example.com"
        )
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
        assert "password" in data

        tenant.refresh_from_db()
        new_owner = tenant.staff_members.get(role="owner").user
        assert new_owner.email == "new.owner@example.com"
        assert new_owner.username == "newowner"
        temp_password = data["password"]

        token_response = api_client.post(
            reverse("token_obtain_pair"),
            {"email": new_owner.email, "password": temp_password},
            format="json",
        )
        assert token_response.status_code == status.HTTP_200_OK


# ---------- throttle wire tests ----------


def test_ops_tenant_mutation_actions_have_throttle():
    """Verifica que ações de mutação do OpsTenantViewSet retornam OpsActionThrottle."""
    from ops.views import OpsTenantViewSet, OpsActionThrottle

    viewset = OpsTenantViewSet()
    for action in ("block_tenant", "unblock_tenant", "reset_owner", "update_plan"):
        viewset.action = action
        throttles = viewset.get_throttles()
        assert any(
            isinstance(t, OpsActionThrottle) for t in throttles
        ), f"Action '{action}' is missing OpsActionThrottle"


def test_ops_tenant_read_actions_do_not_have_ops_action_throttle():
    """Verifica que ações de leitura do OpsTenantViewSet não retornam OpsActionThrottle."""
    from ops.views import OpsTenantViewSet, OpsActionThrottle

    viewset = OpsTenantViewSet()
    viewset.action = "list"
    throttles = viewset.get_throttles()
    assert not any(isinstance(t, OpsActionThrottle) for t in throttles)
