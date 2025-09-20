from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone
from rest_framework import status

from notifications.models import NotificationLog
from ops.models import AccountLockout, OpsSupportAuditLog
from users.models import CustomUser


@pytest.mark.django_db
def test_resend_notification_success(
    api_client,
    ops_user_factory,
    ops_authenticate,
    tenant_with_owner_factory,
):
    support_user = ops_user_factory(CustomUser.OpsRoles.OPS_SUPPORT, "support_ops@example.com")
    tenant, owner = tenant_with_owner_factory("Salon Notify")
    owner.phone_number = "+351999888777"
    owner.save(update_fields=["phone_number"])

    failed_log = NotificationLog.objects.create(
        tenant=tenant,
        user=owner,
        channel="sms",
        notification_type="system",
        title="Agendamento",
        message="Mensagem",
        status="failed",
        metadata={"tries": 1},
    )

    access = ops_authenticate(support_user.email)
    response = api_client.post(
        reverse("ops_support_resend_notification"),
        {"notification_log_id": failed_log.id},
        format="json",
        HTTP_AUTHORIZATION=f"Bearer {access}",
    )
    assert response.status_code == status.HTTP_200_OK
    failed_log.refresh_from_db()
    assert failed_log.status == "sent"
    assert failed_log.metadata.get("ops_resends") == 1
    assert OpsSupportAuditLog.objects.filter(action=OpsSupportAuditLog.Actions.RESEND_NOTIFICATION).exists()


@pytest.mark.django_db
def test_resend_notification_requires_failed_status(
    api_client,
    ops_user_factory,
    ops_authenticate,
    tenant_with_owner_factory,
):
    support_user = ops_user_factory(CustomUser.OpsRoles.OPS_SUPPORT, "support_block@example.com")
    tenant, owner = tenant_with_owner_factory("Salon Notify 2")

    log = NotificationLog.objects.create(
        tenant=tenant,
        user=owner,
        channel="sms",
        notification_type="system",
        title="Teste",
        message="Mensagem",
        status="sent",
    )

    access = ops_authenticate(support_user.email)
    response = api_client.post(
        reverse("ops_support_resend_notification"),
        {"notification_log_id": log.id},
        format="json",
        HTTP_AUTHORIZATION=f"Bearer {access}",
    )
    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert response.data["error"]["code"] == "E403"


@pytest.mark.django_db
def test_clear_lockout_marks_resolved(
    api_client,
    ops_user_factory,
    ops_authenticate,
    tenant_with_owner_factory,
):
    admin = ops_user_factory(CustomUser.OpsRoles.OPS_ADMIN, "lockout_admin@example.com")
    tenant, owner = tenant_with_owner_factory("Salon Secure")
    owner.is_active = False
    owner.save(update_fields=["is_active"])

    lockout = AccountLockout.objects.create(
        user=owner,
        tenant=tenant,
        reason="Muitas tentativas",
        locked_at=timezone.now() - timedelta(hours=1),
    )

    access = ops_authenticate(admin.email)
    response = api_client.post(
        reverse("ops_support_clear_lockout"),
        {"lockout_id": lockout.id, "note": "Unlock manual"},
        format="json",
        HTTP_AUTHORIZATION=f"Bearer {access}",
    )
    assert response.status_code == status.HTTP_200_OK
    lockout.refresh_from_db()
    owner.refresh_from_db()
    assert lockout.resolved_at is not None
    assert owner.is_active is True
    assert OpsSupportAuditLog.objects.filter(action=OpsSupportAuditLog.Actions.CLEAR_LOCKOUT).exists()


@pytest.mark.django_db
def test_support_cannot_clear_lockout(
    api_client,
    ops_user_factory,
    ops_authenticate,
    tenant_with_owner_factory,
):
    support_user = ops_user_factory(CustomUser.OpsRoles.OPS_SUPPORT, "lockout_support@example.com")
    tenant, owner = tenant_with_owner_factory("Salon Secure 2")

    lockout = AccountLockout.objects.create(
        user=owner,
        tenant=tenant,
        reason="Incidentes",
    )

    access = ops_authenticate(support_user.email)
    response = api_client.post(
        reverse("ops_support_clear_lockout"),
        {"lockout_id": lockout.id},
        format="json",
        HTTP_AUTHORIZATION=f"Bearer {access}",
    )
    assert response.status_code == status.HTTP_403_FORBIDDEN
