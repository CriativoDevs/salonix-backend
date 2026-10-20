"""
Testes do management command `auto_generate_monthly_slots` (BE-SLOTS-04, #559).
"""

from datetime import date, timedelta

import pytest
from django.core.management import call_command
from django.utils import timezone

from core.models import Professional, ScheduleSlot
from users.models import CustomUser, Tenant, TenantBusinessHours, TenantStaffMember

MON = 0


def _make_setup(slug, *, auto_generate=True):
    tenant = Tenant.objects.create(
        name=f"Salon {slug}",
        slug=slug,
        is_active=True,
        timezone="Europe/Lisbon",
        auto_generate_slots_enabled=auto_generate,
    )
    owner = CustomUser.objects.create_user(
        username=f"owner_{slug}",
        email=f"owner_{slug}@example.com",
        password="Pass123!",
        tenant=tenant,
    )
    staff = TenantStaffMember.objects.create(
        tenant=tenant,
        user=owner,
        role=TenantStaffMember.Role.OWNER,
        status=TenantStaffMember.Status.ACTIVE,
    )
    prof_user = CustomUser.objects.create_user(
        username=f"prof_{slug}",
        email=f"prof_{slug}@example.com",
        password="Pass123!",
        tenant=tenant,
    )
    professional = Professional.objects.create(
        tenant=tenant,
        user=prof_user,
        staff_member=staff,
        name="Ana Lima",
        is_active=True,
    )
    return tenant, owner, professional


def _add_bh(tenant, day, start="09:00", end="12:00"):
    TenantBusinessHours.objects.create(
        tenant=tenant, day_of_week=day, start_time=start, end_time=end, is_active=True
    )


def _next_month_mondays_count():
    """Conta quantas segundas-feiras existem no próximo mês (a partir de hoje)."""
    today = timezone.localdate()
    if today.month == 12:
        first = today.replace(year=today.year + 1, month=1, day=1)
    else:
        first = today.replace(month=today.month + 1, day=1)
    if first.month == 12:
        last = first.replace(year=first.year + 1, month=1, day=1) - timedelta(days=1)
    else:
        last = first.replace(month=first.month + 1, day=1) - timedelta(days=1)
    count = 0
    d = first
    while d <= last:
        if d.weekday() == MON:
            count += 1
        d += timedelta(days=1)
    return count


@pytest.mark.django_db
class TestAutoGenerateMonthlySlots:
    def test_generates_slots_for_enabled_tenant_with_business_hours(self):
        tenant, _owner, professional = _make_setup("auto-slots-ok", auto_generate=True)
        # Interval fixo do command é 30min -> 09:00-10:00 = 2 slots por segunda.
        _add_bh(tenant, MON, "09:00", "10:00")

        call_command("auto_generate_monthly_slots")

        expected = _next_month_mondays_count() * 2
        created = ScheduleSlot.objects.filter(
            tenant=tenant, professional=professional
        ).count()
        assert created == expected
        assert expected > 0

    def test_tenant_with_flag_disabled_is_ignored(self):
        tenant, _owner, professional = _make_setup(
            "auto-slots-off", auto_generate=False
        )
        _add_bh(tenant, MON, "09:00", "10:00")

        call_command("auto_generate_monthly_slots")

        assert (
            ScheduleSlot.objects.filter(tenant=tenant, professional=professional).count()
            == 0
        )

    def test_tenant_without_business_hours_is_skipped_without_error(self):
        tenant, _owner, professional = _make_setup(
            "auto-slots-nobh", auto_generate=True
        )
        # Sem TenantBusinessHours configurado.

        call_command("auto_generate_monthly_slots")

        assert (
            ScheduleSlot.objects.filter(tenant=tenant, professional=professional).count()
            == 0
        )

    def test_idempotent_running_twice_does_not_duplicate(self):
        tenant, _owner, professional = _make_setup(
            "auto-slots-idem", auto_generate=True
        )
        _add_bh(tenant, MON, "09:00", "11:00")  # 2 slots de 60min por segunda

        call_command("auto_generate_monthly_slots")
        first_count = ScheduleSlot.objects.filter(
            tenant=tenant, professional=professional
        ).count()
        assert first_count > 0

        call_command("auto_generate_monthly_slots")
        second_count = ScheduleSlot.objects.filter(
            tenant=tenant, professional=professional
        ).count()
        assert second_count == first_count

    def test_inactive_professional_is_ignored(self):
        tenant, _owner, professional = _make_setup(
            "auto-slots-inactive-prof", auto_generate=True
        )
        _add_bh(tenant, MON, "09:00", "10:00")
        professional.is_active = False
        professional.save(update_fields=["is_active"])

        call_command("auto_generate_monthly_slots")

        assert (
            ScheduleSlot.objects.filter(tenant=tenant, professional=professional).count()
            == 0
        )

    def test_tenants_isolated(self):
        tenant_a, _owner_a, prof_a = _make_setup("auto-slots-iso-a", auto_generate=True)
        tenant_b, _owner_b, prof_b = _make_setup(
            "auto-slots-iso-b", auto_generate=False
        )
        _add_bh(tenant_a, MON, "09:00", "10:00")
        _add_bh(tenant_b, MON, "09:00", "10:00")

        call_command("auto_generate_monthly_slots")

        assert ScheduleSlot.objects.filter(tenant=tenant_a).count() > 0
        assert ScheduleSlot.objects.filter(tenant=tenant_b).count() == 0
