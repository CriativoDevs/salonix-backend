"""
BE-TRIAL-01: Tenant.is_trial_expired() — fonte de trial independente do Stripe.

Sem checkout no registro, nenhuma Subscription Stripe é criada para disparar o
webhook que alimenta UserFeatureFlags.pro_status. is_in_trial() (que depende
disso) ficaria sempre False, tanto durante quanto depois do trial. Este método
usa Tenant.created_at + settings.STRIPE_TRIAL_PERIOD_DAYS como fonte própria.
"""

from datetime import timedelta

import pytest
from django.conf import settings
from django.utils import timezone

from users.models import Tenant, UserFeatureFlags


def _set_created_at(tenant, when):
    Tenant.objects.filter(pk=tenant.pk).update(created_at=when)
    tenant.refresh_from_db()


@pytest.mark.django_db
def test_is_trial_expired_false_within_trial_window(tenant_fixture):
    _set_created_at(tenant_fixture, timezone.now() - timedelta(days=1))

    assert tenant_fixture.is_trial_expired() is False


@pytest.mark.django_db
def test_is_trial_expired_true_after_trial_window(tenant_fixture):
    trial_days = settings.STRIPE_TRIAL_PERIOD_DAYS
    _set_created_at(
        tenant_fixture, timezone.now() - timedelta(days=trial_days + 1)
    )

    assert tenant_fixture.is_trial_expired() is True


@pytest.mark.django_db
def test_is_trial_expired_false_when_paid_subscription_active(
    tenant_fixture, user_fixture
):
    trial_days = settings.STRIPE_TRIAL_PERIOD_DAYS
    _set_created_at(
        tenant_fixture, timezone.now() - timedelta(days=trial_days + 1)
    )
    ff = user_fixture.featureflags
    ff.pro_status = UserFeatureFlags.STATUS_ACTIVE
    ff.save(update_fields=["pro_status"])

    assert tenant_fixture.is_trial_expired() is False


@pytest.mark.django_db
def test_is_trial_expired_false_for_promotional_billing(tenant_fixture):
    trial_days = settings.STRIPE_TRIAL_PERIOD_DAYS
    _set_created_at(
        tenant_fixture, timezone.now() - timedelta(days=trial_days + 1)
    )
    tenant_fixture.billing_mode = Tenant.BILLING_MODE_PROMOTIONAL
    tenant_fixture.save(update_fields=["billing_mode"])

    assert tenant_fixture.is_trial_expired() is False


@pytest.mark.django_db
def test_is_trial_expired_true_exactly_at_boundary(tenant_fixture):
    trial_days = settings.STRIPE_TRIAL_PERIOD_DAYS
    _set_created_at(
        tenant_fixture, timezone.now() - timedelta(days=trial_days)
    )

    assert tenant_fixture.is_trial_expired() is True


@pytest.mark.django_db
def test_is_trial_expired_false_when_trial_days_misconfigured_to_zero(
    tenant_fixture, settings
):
    """STRIPE_TRIAL_DAYS ausente/malformado no ambiente cai no default=0
    (users/models.py: _safe_int(env_get("STRIPE_TRIAL_DAYS", "14"), default=0)).

    Sem esse guard, um tenant criado agora mesmo (created_at ~ now) seria
    marcado como trial expirado na hora do cadastro — bloqueando a plataforma
    inteira por uma falha de configuração, não por falta de pagamento. Preferimos
    falhar aberto (não bloquear) a um blackout completo por env var quebrada.
    """
    settings.STRIPE_TRIAL_PERIOD_DAYS = 0
    _set_created_at(tenant_fixture, timezone.now())

    assert tenant_fixture.is_trial_expired() is False
