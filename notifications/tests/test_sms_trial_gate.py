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


@pytest.mark.django_db
def test_sms_blocked_for_promotional_tenant_without_stripe(tenant_fixture, user_fixture):
    """Caso real que causou custo indevido: tenant billing_mode=promotional nunca
    passa pelo Stripe, então is_in_trial() é sempre False — mas o tenant também não é
    um cliente pagante real, então o SMS deve continuar bloqueado."""
    tenant_fixture.billing_mode = Tenant.BILLING_MODE_PROMOTIONAL
    tenant_fixture.save(update_fields=["billing_mode"])
    _set_owner_status(user_fixture, UserFeatureFlags.STATUS_INCOMPLETE)
    _fund_tenant(tenant_fixture)

    result = credit_service.can_send_message(tenant_fixture, "sms")

    assert result["can_send"] is False


@pytest.mark.django_db
def test_sms_blocked_when_no_owner_featureflags(tenant_fixture, user_fixture):
    """Tenant sem qualquer subscrição Stripe confirmada (status default 'incomplete')
    também não deve poder enviar SMS, mesmo fora do trial."""
    _set_owner_status(user_fixture, UserFeatureFlags.STATUS_INCOMPLETE)
    _fund_tenant(tenant_fixture)

    result = credit_service.can_send_message(tenant_fixture, "sms")

    assert result["can_send"] is False


@pytest.mark.django_db
def test_sms_allowed_for_past_due_paid_tenant(tenant_fixture, user_fixture):
    """past_due ainda conta como 'já pagou pelo menos uma vez' — não deve ser tratado
    como não-pagante (a cobrança pode estar só temporariamente em falha)."""
    _set_owner_status(user_fixture, UserFeatureFlags.STATUS_PAST_DUE)
    _fund_tenant(tenant_fixture)

    result = credit_service.can_send_message(tenant_fixture, "sms")

    assert result["can_send"] is True
