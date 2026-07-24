from decimal import Decimal

import pytest

from django.core.management import call_command

from users.models import CommLedger, Tenant, TenantStaffMember, UserFeatureFlags
from django.contrib.auth import get_user_model

User = get_user_model()


def _make_paying_tenant(*, is_founder, comm_credit_eur):
    plan_tier = Tenant.PLAN_BASIC
    tenant = Tenant.objects.create(
        name="Tenant Pagante",
        slug=f"tenant-pagante-{'founder' if is_founder else 'basic'}-{comm_credit_eur}",
        plan_tier=plan_tier,
        is_founder=is_founder,
    )
    Tenant.objects.filter(pk=tenant.pk).update(comm_credit_eur=comm_credit_eur)
    tenant.refresh_from_db()
    tenant.comm_ledger.all().delete()

    user = User.objects.create_user(
        username=f"owner-{tenant.slug}",
        email=f"{tenant.slug}@example.com",
        tenant=tenant,
    )
    TenantStaffMember.objects.create(
        tenant=tenant,
        user=user,
        role=TenantStaffMember.Role.OWNER,
        status=TenantStaffMember.Status.ACTIVE,
    )
    user.featureflags.pro_status = UserFeatureFlags.STATUS_ACTIVE
    user.featureflags.save(update_fields=["pro_status"])
    return tenant


@pytest.mark.django_db
def test_founder_tenant_with_residual_balance_tops_up_to_two_euros():
    tenant = _make_paying_tenant(is_founder=True, comm_credit_eur=Decimal("1.00"))

    call_command("renew_monthly_communication_credits")

    tenant.refresh_from_db()
    assert tenant.comm_credit_eur == Decimal("2.00")


@pytest.mark.django_db
def test_founder_tenant_with_zero_balance_tops_up_to_two_euros():
    tenant = _make_paying_tenant(is_founder=True, comm_credit_eur=Decimal("0.00"))

    call_command("renew_monthly_communication_credits")

    tenant.refresh_from_db()
    assert tenant.comm_credit_eur == Decimal("2.00")


@pytest.mark.django_db
def test_founder_tenant_above_cap_is_not_reduced_and_no_ledger_entry():
    tenant = _make_paying_tenant(is_founder=True, comm_credit_eur=Decimal("3.00"))

    call_command("renew_monthly_communication_credits")

    tenant.refresh_from_db()
    assert tenant.comm_credit_eur == Decimal("3.00")
    assert not tenant.comm_ledger.filter(
        transaction_type=CommLedger.TransactionType.BONUS,
        description__icontains="Renovação mensal",
    ).exists()


@pytest.mark.django_db
def test_tenant_in_trial_does_not_get_renewed():
    tenant = _make_paying_tenant(is_founder=True, comm_credit_eur=Decimal("0.00"))
    owner = tenant.staff_members.get(role=TenantStaffMember.Role.OWNER)
    owner.user.featureflags.pro_status = UserFeatureFlags.STATUS_TRIALING
    owner.user.featureflags.save(update_fields=["pro_status"])

    call_command("renew_monthly_communication_credits")

    tenant.refresh_from_db()
    assert tenant.comm_credit_eur == Decimal("0.00")


@pytest.mark.django_db
def test_renewal_creates_ledger_entry_when_balance_rises():
    tenant = _make_paying_tenant(is_founder=True, comm_credit_eur=Decimal("1.00"))

    call_command("renew_monthly_communication_credits")

    entry = tenant.comm_ledger.filter(
        transaction_type=CommLedger.TransactionType.BONUS,
        description__icontains="Renovação mensal",
    ).first()
    assert entry is not None
    assert entry.balance_before == Decimal("1.00")
    assert entry.balance_after == Decimal("2.00")
