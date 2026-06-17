"""
BE-PLANS-02: bloqueio de SMS durante o período de teste (trial).

O gate vive em CreditService.can_send_message e é SMS-only: WhatsApp, Email e Web
Push não são afetados. Liberação automática quando a subscrição deixa de ser
`trialing` (status `active`).
"""

from decimal import Decimal

import pytest

from notifications.credit_service import credit_service
from users.models import Tenant, UserFeatureFlags


def _set_owner_status(user, status):
    ff = user.featureflags
    ff.pro_status = status
    ff.save(update_fields=["pro_status"])


def _fund_tenant(tenant):
    Tenant.objects.filter(pk=tenant.pk).update(
        comm_credit_eur=Decimal("10.00"),
        sms_enabled=True,
        whatsapp_enabled=True,
    )
    tenant.refresh_from_db()


@pytest.mark.django_db
def test_sms_blocked_during_trial_even_with_balance(tenant_fixture, user_fixture):
    _set_owner_status(user_fixture, UserFeatureFlags.STATUS_TRIALING)
    _fund_tenant(tenant_fixture)

    result = credit_service.can_send_message(tenant_fixture, "sms")

    assert result["can_send"] is False
    assert "teste" in result["reason"].lower()


@pytest.mark.django_db
def test_whatsapp_not_blocked_during_trial(tenant_fixture, user_fixture):
    _set_owner_status(user_fixture, UserFeatureFlags.STATUS_TRIALING)
    _fund_tenant(tenant_fixture)

    result = credit_service.can_send_message(tenant_fixture, "whatsapp")

    assert result["can_send"] is True


@pytest.mark.django_db
def test_sms_allowed_after_trial(tenant_fixture, user_fixture):
    _set_owner_status(user_fixture, UserFeatureFlags.STATUS_ACTIVE)
    _fund_tenant(tenant_fixture)

    result = credit_service.can_send_message(tenant_fixture, "sms")

    assert result["can_send"] is True
