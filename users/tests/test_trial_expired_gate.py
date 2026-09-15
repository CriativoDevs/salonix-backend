"""
BE-TRIAL-02: HasActiveTrialOrSubscription -- bloqueio brando pós-trial.

Aplicado a endpoints não-críticos (TenantStaffView, TenantModulesSettingsView),
espelhando onde IsActiveTenant já é usado. Endpoints de checkout/billing/auth
nunca recebem esta permission -- o tenant precisa continuar acessando-os para
poder pagar e sair do bloqueio.
"""

from datetime import timedelta

import pytest
from django.conf import settings
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from users.models import Tenant, UserFeatureFlags


def _backdate_past_trial(tenant):
    trial_days = settings.STRIPE_TRIAL_PERIOD_DAYS
    Tenant.objects.filter(pk=tenant.pk).update(
        created_at=timezone.now() - timedelta(days=trial_days + 1)
    )
    tenant.refresh_from_db()


@pytest.mark.django_db
def test_staff_endpoint_blocked_with_402_after_trial_expired(
    tenant_fixture, user_fixture
):
    _backdate_past_trial(tenant_fixture)
    client = APIClient()
    client.force_authenticate(user=user_fixture)

    response = client.get("/api/users/staff/")

    assert response.status_code == status.HTTP_402_PAYMENT_REQUIRED
    assert response.data["error"]["details"]["code"] == "trial_expired"


@pytest.mark.django_db
def test_staff_endpoint_allowed_within_trial(tenant_fixture, user_fixture):
    client = APIClient()
    client.force_authenticate(user=user_fixture)

    response = client.get("/api/users/staff/")

    assert response.status_code == status.HTTP_200_OK


@pytest.mark.django_db
def test_staff_endpoint_allowed_after_trial_expired_with_paid_subscription(
    tenant_fixture, user_fixture
):
    _backdate_past_trial(tenant_fixture)
    ff = user_fixture.featureflags
    ff.pro_status = UserFeatureFlags.STATUS_ACTIVE
    ff.save(update_fields=["pro_status"])
    client = APIClient()
    client.force_authenticate(user=user_fixture)

    response = client.get("/api/users/staff/")

    assert response.status_code == status.HTTP_200_OK


@pytest.mark.django_db
def test_staff_endpoint_allowed_for_promotional_tenant_past_grace(
    tenant_fixture, user_fixture
):
    _backdate_past_trial(tenant_fixture)
    tenant_fixture.billing_mode = Tenant.BILLING_MODE_PROMOTIONAL
    tenant_fixture.save(update_fields=["billing_mode"])
    client = APIClient()
    client.force_authenticate(user=user_fixture)

    response = client.get("/api/users/staff/")

    assert response.status_code == status.HTTP_200_OK


@pytest.mark.django_db
def test_bootstrap_endpoint_never_blocked_by_trial_gate(tenant_fixture, user_fixture):
    """MeTenantView (bootstrap) nunca recebe este gate: o FE precisa ler
    is_trial_expired/onboarding_state dali para decidir mostrar a tela de
    bloqueio -- se o próprio bootstrap desse 402, o FE nunca saberia o motivo."""
    _backdate_past_trial(tenant_fixture)
    client = APIClient()
    client.force_authenticate(user=user_fixture)

    response = client.get("/api/users/me/tenant/")

    assert response.status_code == status.HTTP_200_OK
    assert response.data["is_trial_expired"] is True
