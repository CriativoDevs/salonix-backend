"""
BE-TRIAL-02: deactivate_unpaid_signups virou no-op.

O comando existia para o fluxo antigo (checkout no registro): um tenant que
abandonava o checkout mantinha acesso completo indefinidamente, então o cron
desativava a conta após o período de carência. Com o checkout removido do
registro (BE-TRIAL-01), todo tenant sem pagamento passaria por esse mesmo
caminho após o trial -- desativar contradiz a decisão de bloqueio brando
indefinido (Tenant.is_trial_expired() + HasActiveTrialOrSubscription já
bloqueiam o acesso sem apagar/desativar). O comando é mantido como no-op só
para não quebrar o Cron Job já configurado em produção.
"""

from datetime import timedelta

import pytest
from django.core.management import call_command
from django.utils import timezone

from users.models import Tenant


def _backdate(tenant, days):
    Tenant.objects.filter(pk=tenant.pk).update(
        created_at=timezone.now() - timedelta(days=days)
    )
    tenant.refresh_from_db()


@pytest.mark.django_db
def test_never_deactivates_tenant_past_grace_without_payment(
    tenant_fixture, user_fixture
):
    _backdate(tenant_fixture, days=100)

    call_command("deactivate_unpaid_signups")

    tenant_fixture.refresh_from_db()
    assert tenant_fixture.is_active is True
