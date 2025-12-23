import pytest
from django.urls import reverse
from rest_framework import status
from users.models import CustomUser
from ops.models import OpsSupportAuditLog
from django.utils import timezone


@pytest.mark.django_db
class TestOpsAuditLogsEndpoints:
    def test_list_audit_logs_as_admin(
        self,
        api_client,
        ops_user_factory,
        ops_authenticate,
    ):
        admin = ops_user_factory(
            CustomUser.OpsRoles.OPS_ADMIN, "admin_audit@example.com"
        )

        # Create some logs
        OpsSupportAuditLog.objects.create(
            actor=admin, action="test_action_1", payload={"key": "value1"}
        )
        OpsSupportAuditLog.objects.create(
            actor=admin, action="test_action_2", payload={"key": "value2"}
        )

        access = ops_authenticate(admin.email)
        response = api_client.get(
            reverse("ops-audit-logs-list"),
            HTTP_AUTHORIZATION=f"Bearer {access}",
        )

        assert response.status_code == status.HTTP_200_OK

        results = (
            response.data.get("results")
            if isinstance(response.data, dict)
            else response.data
        )
        
        # Filter only test actions to ignore side-effect logs (like login attempts)
        test_logs = [r for r in results if r["action"] in ["test_action_1", "test_action_2"]]
        
        assert len(test_logs) == 2
        # Ordered by -created_at, so the last created comes first
        assert test_logs[0]["action"] == "test_action_2"
        assert test_logs[1]["action"] == "test_action_1"

    def test_list_audit_logs_as_support_forbidden(
        self,
        api_client,
        ops_user_factory,
        ops_authenticate,
    ):
        support = ops_user_factory(
            CustomUser.OpsRoles.OPS_SUPPORT, "support_audit@example.com"
        )

        access = ops_authenticate(support.email)
        response = api_client.get(
            reverse("ops-audit-logs-list"),
            HTTP_AUTHORIZATION=f"Bearer {access}",
        )

        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_filter_audit_logs(
        self,
        api_client,
        ops_user_factory,
        ops_authenticate,
    ):
        admin = ops_user_factory(
            CustomUser.OpsRoles.OPS_ADMIN, "admin_filter@example.com"
        )
        other_user = ops_user_factory(
            CustomUser.OpsRoles.OPS_ADMIN, "other_filter@example.com"
        )

        # Log 1: By admin, Action A
        log1 = OpsSupportAuditLog.objects.create(
            actor=admin, action="action_a", payload={}
        )
        # Log 2: By other, Action B
        log2 = OpsSupportAuditLog.objects.create(
            actor=other_user, action="action_b", payload={}
        )

        access = ops_authenticate(admin.email)

        # Filter by actor_id
        response = api_client.get(
            reverse("ops-audit-logs-list") + f"?actor_id={admin.id}",
            HTTP_AUTHORIZATION=f"Bearer {access}",
        )
        assert response.status_code == status.HTTP_200_OK
        results = (
            response.data.get("results")
            if isinstance(response.data, dict)
            else response.data
        )
        # Should only see log1 (by admin)
        assert len(results) == 1
        assert results[0]["id"] == log1.id

        # Filter by action
        response = api_client.get(
            reverse("ops-audit-logs-list") + "?action=action_b",
            HTTP_AUTHORIZATION=f"Bearer {access}",
        )
        assert response.status_code == status.HTTP_200_OK
        results = (
            response.data.get("results")
            if isinstance(response.data, dict)
            else response.data
        )
        # Should only see log2 (action_b)
        assert len(results) == 1
        assert results[0]["id"] == log2.id
