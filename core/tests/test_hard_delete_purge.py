"""
BE-RGPD-01 / Art. 17: verificacao de que o hard-delete purga a PII.

`hard_delete_tenant` apaga o tenant (cascade), removendo efetivamente os dados
pessoais — nao apenas desativa. Guard de regressao para o direito ao apagamento.
"""

from datetime import timedelta

import pytest
from django.test import override_settings
from django.utils import timezone

from core.models import SalonCustomer
from core.tasks import hard_delete_tenant
from users.models import CustomUser, Tenant, TenantStaffMember


@pytest.mark.django_db
def test_hard_delete_purges_tenant_pii(tmp_path):
    tenant = Tenant.objects.create(
        name="Doomed Salon",
        slug="doomed-salon",
        plan_tier="standard",
        status=Tenant.STATUS_CANCELLED,
        cancelled_at=timezone.now() - timedelta(days=100),
    )
    owner = CustomUser.objects.create_user(
        username="doomed_owner",
        email="doomed@example.com",
        password="x",
        tenant=tenant,
    )
    TenantStaffMember.objects.create(
        tenant=tenant, user=owner, role=TenantStaffMember.Role.OWNER
    )
    customer = SalonCustomer.objects.create(
        tenant=tenant, name="PII Person", email="pii@example.com"
    )

    with override_settings(BACKUP_ROOT=tmp_path):
        result = hard_delete_tenant.apply(args=[tenant.id]).get()

    assert result["success"] is True
    # PII purgada por cascade: tenant e cliente deixam de existir
    assert not Tenant.objects.filter(pk=tenant.pk).exists()
    assert not SalonCustomer.objects.filter(pk=customer.pk).exists()
    assert not CustomUser.objects.filter(pk=owner.pk).exists()
