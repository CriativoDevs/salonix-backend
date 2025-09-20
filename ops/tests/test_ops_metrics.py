from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone
from rest_framework import status

from decimal import Decimal

from notifications.models import NotificationLog
from ops.models import OpsAlert, OpsSupportAuditLog
from users.models import CustomUser, Tenant


@pytest.mark.django_db
def test_metrics_overview_endpoint(
    api_client,
    ops_user_factory,
    ops_authenticate,
    tenant_with_owner_factory,
):
    support_user = ops_user_factory(CustomUser.OpsRoles.OPS_SUPPORT, "metrics_ops@example.com")
    tenant_basic, owner_basic = tenant_with_owner_factory("Salon Metrics Basic", plan_tier=Tenant.PLAN_BASIC)
    tenant_pro, owner_pro = tenant_with_owner_factory("Salon Metrics Pro", plan_tier=Tenant.PLAN_PRO)

    now = timezone.now()

    log = NotificationLog.objects.create(
        tenant=tenant_basic,
        user=owner_basic,
        channel="sms",
        notification_type="system",
        title="Teste",
        message="Mensagem",
        status="sent",
    )
    NotificationLog.objects.filter(pk=log.pk).update(created_at=now - timedelta(days=1))

    log2 = NotificationLog.objects.create(
        tenant=tenant_pro,
        user=owner_pro,
        channel="whatsapp",
        notification_type="system",
        title="Teste",
        message="Mensagem",
        status="delivered",
    )
    NotificationLog.objects.filter(pk=log2.pk).update(created_at=now - timedelta(days=2))

    owner_basic.featureflags.trial_until = now + timedelta(days=3)
    owner_basic.featureflags.save(update_fields=["trial_until"])

    OpsAlert.objects.create(
        category=OpsAlert.Categories.SECURITY_INCIDENT,
        severity=OpsAlert.Severity.CRITICAL,
        message="Falha de login suspeita",
        tenant=tenant_basic,
    )

    access = ops_authenticate(support_user.email)
    response = api_client.get(
        reverse("ops_metrics_overview"),
        HTTP_AUTHORIZATION=f"Bearer {access}",
    )
    assert response.status_code == status.HTTP_200_OK

    data = response.data
    active_expected = Tenant.objects.filter(is_active=True).count()
    assert data["totals"]["active_tenants"] == active_expected
    assert data["totals"]["trials_expiring_7d"] == 1
    assert data["totals"]["alerts_open"] == 1

    plan_pricing = {
        Tenant.PLAN_BASIC: Decimal("29.00"),
        Tenant.PLAN_STANDARD: Decimal("59.00"),
        Tenant.PLAN_PRO: Decimal("99.00"),
    }
    expected_mrr = Decimal("0.00")
    for tenant in Tenant.objects.filter(is_active=True):
        expected_mrr += plan_pricing.get(tenant.plan_tier, Decimal("0.00"))

    assert data["mrr_estimated"]["total"] == f"{expected_mrr:.2f}"
    assert len(data["notification_daily"]) == 7
    assert data["notification_daily"][0]["channels"] == {}


@pytest.mark.django_db
def test_alerts_list_and_resolve(
    api_client,
    ops_user_factory,
    ops_authenticate,
):
    support_user = ops_user_factory(CustomUser.OpsRoles.OPS_SUPPORT, "alerts_ops@example.com")
    alert_active = OpsAlert.objects.create(
        category=OpsAlert.Categories.NOTIFICATION_FAILURE,
        severity=OpsAlert.Severity.WARNING,
        message="SMS falhou",
    )
    OpsAlert.objects.create(
        category=OpsAlert.Categories.SECURITY_INCIDENT,
        severity=OpsAlert.Severity.CRITICAL,
        message="Tentativa de acesso",
        resolved_at=timezone.now(),
    )

    access = ops_authenticate(support_user.email)

    response = api_client.get(
        reverse("ops-alerts-list"),
        HTTP_AUTHORIZATION=f"Bearer {access}",
    )
    assert response.status_code == status.HTTP_200_OK
    assert len(response.data) == 1
    assert response.data[0]["id"] == alert_active.id

    resolve_resp = api_client.post(
        reverse("ops-alerts-resolve", kwargs={"pk": alert_active.id}),
        HTTP_AUTHORIZATION=f"Bearer {access}",
    )
    assert resolve_resp.status_code == status.HTTP_200_OK
    alert_active.refresh_from_db()
    assert alert_active.is_resolved
    assert OpsSupportAuditLog.objects.filter(action=OpsSupportAuditLog.Actions.RESOLVE_ALERT).exists()

    resolved_list = api_client.get(
        reverse("ops-alerts-list"),
        {"resolved": "true"},
        HTTP_AUTHORIZATION=f"Bearer {access}",
    )
    assert resolved_list.status_code == status.HTTP_200_OK
    assert any(item["id"] == alert_active.id for item in resolved_list.data)
