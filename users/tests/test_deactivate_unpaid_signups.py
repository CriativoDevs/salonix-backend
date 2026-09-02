"""
Regressão de produção: um tenant nasce com billing_mode=Stripe, is_active=True
e (se havia vaga) is_founder=True já no cadastro (users/serializers.py), antes
de qualquer pagamento. Se o checkout nunca é concluído, nada revoga esse
acesso. `deactivate_unpaid_signups` fecha essa lacuna.
"""

from datetime import timedelta

import pytest
from django.core.management import call_command
from django.utils import timezone

from users.models import Tenant, UserFeatureFlags


def _backdate(tenant, days):
    Tenant.objects.filter(pk=tenant.pk).update(
        created_at=timezone.now() - timedelta(days=days)
    )
    tenant.refresh_from_db()


@pytest.mark.django_db
def test_deactivates_tenant_past_grace_without_payment(tenant_fixture, user_fixture):
    _backdate(tenant_fixture, days=15)

    call_command("deactivate_unpaid_signups")

    tenant_fixture.refresh_from_db()
    assert tenant_fixture.is_active is False


@pytest.mark.django_db
def test_keeps_tenant_still_within_grace_period(tenant_fixture, user_fixture):
    _backdate(tenant_fixture, days=5)

    call_command("deactivate_unpaid_signups")

    tenant_fixture.refresh_from_db()
    assert tenant_fixture.is_active is True


@pytest.mark.django_db
def test_keeps_tenant_currently_trialing(tenant_fixture, user_fixture):
    _backdate(tenant_fixture, days=15)
    ff = user_fixture.featureflags
    ff.pro_status = UserFeatureFlags.STATUS_TRIALING
    ff.save(update_fields=["pro_status"])

    call_command("deactivate_unpaid_signups")

    tenant_fixture.refresh_from_db()
    assert tenant_fixture.is_active is True


@pytest.mark.django_db
def test_keeps_tenant_with_confirmed_paid_subscription(tenant_fixture, user_fixture):
    _backdate(tenant_fixture, days=15)
    ff = user_fixture.featureflags
    ff.pro_status = UserFeatureFlags.STATUS_ACTIVE
    ff.save(update_fields=["pro_status"])

    call_command("deactivate_unpaid_signups")

    tenant_fixture.refresh_from_db()
    assert tenant_fixture.is_active is True


@pytest.mark.django_db
def test_ignores_promotional_tenants(tenant_fixture, user_fixture):
    _backdate(tenant_fixture, days=15)
    tenant_fixture.billing_mode = Tenant.BILLING_MODE_PROMOTIONAL
    tenant_fixture.save(update_fields=["billing_mode"])

    call_command("deactivate_unpaid_signups")

    tenant_fixture.refresh_from_db()
    assert tenant_fixture.is_active is True
