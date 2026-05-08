import uuid
import pytest
from datetime import date, timedelta
from decimal import Decimal
from unittest.mock import patch

from django.utils import timezone
from django.test import override_settings
from rest_framework.test import APIClient

_NO_CACHE = {"default": {"BACKEND": "django.core.cache.backends.dummy.DummyCache"}}

from django.contrib.auth import get_user_model
from users.models import Tenant, UserFeatureFlags
from core.models import Appointment, Professional, SalonCustomer, ScheduleSlot, Service
from reports.models import DailyReportAggregate

User = get_user_model()

# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_tenant():
    s = uuid.uuid4().hex[:8]
    return Tenant.objects.create(
        slug=f"t-{s}", name=f"Tenant {s}",
        plan_tier=Tenant.PLAN_PRO, reports_enabled=True,
    )


def _make_user(tenant, *, is_pro=True):
    u = User.objects.create_user(
        username=f"u-{uuid.uuid4().hex[:8]}",
        email=f"u-{uuid.uuid4().hex[:8]}@test.com",
        password="x",
        tenant=tenant,
    )
    UserFeatureFlags.objects.update_or_create(
        user=u, defaults={"is_pro": is_pro, "reports_enabled": True}
    )
    return u


def _make_appointment(tenant, user, *, day: date, status="completed", price=Decimal("50")):
    """Creates an Appointment whose slot falls on `day`."""
    start = timezone.make_aware(
        timezone.datetime(day.year, day.month, day.day, 10, 0)
    )
    svc = Service.objects.create(
        tenant=tenant, user=user, name=f"Svc-{uuid.uuid4().hex[:4]}",
        duration_minutes=30, price_eur=price,
    )
    prof = Professional.objects.create(tenant=tenant, user=user, name="Prof")
    cust = SalonCustomer.objects.create(
        tenant=tenant, name="Cust", email=f"c-{uuid.uuid4().hex[:6]}@t.com"
    )
    slot = ScheduleSlot.objects.create(
        tenant=tenant, professional=prof,
        start_time=start, end_time=start + timezone.timedelta(minutes=30),
        is_available=False, status="booked",
    )
    return Appointment.objects.create(
        tenant=tenant, client=user, customer=cust,
        service=svc, professional=prof, slot=slot, status=status,
    )


def _client(user):
    c = APIClient()
    c.force_authenticate(user)
    return c


# ── Backfill tests ────────────────────────────────────────────────────────────


@pytest.mark.django_db
def test_backfill_creates_aggregates_for_existing_appointments():
    tenant = _make_tenant()
    user = _make_user(tenant)
    today = date.today()
    yesterday = today - timedelta(days=1)
    two_days_ago = today - timedelta(days=2)

    _make_appointment(tenant, user, day=yesterday, status="completed", price=Decimal("100"))
    _make_appointment(tenant, user, day=yesterday, status="cancelled", price=Decimal("50"))
    _make_appointment(tenant, user, day=two_days_ago, status="paid", price=Decimal("80"))

    from reports.backfill import backfill_tenant
    result = backfill_tenant(tenant.id, since=two_days_ago, until=yesterday)

    assert result["created"] == 2
    assert result["updated"] == 0

    agg_y = DailyReportAggregate.objects.get(tenant=tenant, date=yesterday)
    assert agg_y.appointments_total == 2
    assert agg_y.appointments_completed == 1
    assert agg_y.revenue_total == Decimal("100")

    agg_2d = DailyReportAggregate.objects.get(tenant=tenant, date=two_days_ago)
    assert agg_2d.appointments_total == 1
    assert agg_2d.appointments_completed == 1
    assert agg_2d.revenue_total == Decimal("80")


@pytest.mark.django_db
def test_backfill_updates_existing_aggregates():
    tenant = _make_tenant()
    user = _make_user(tenant)
    yesterday = date.today() - timedelta(days=1)

    DailyReportAggregate.objects.create(
        tenant=tenant, date=yesterday,
        appointments_total=99, appointments_completed=99, revenue_total=Decimal("9999"),
    )
    _make_appointment(tenant, user, day=yesterday, status="completed", price=Decimal("50"))

    from reports.backfill import backfill_tenant
    result = backfill_tenant(tenant.id, since=yesterday, until=yesterday)

    assert result["updated"] == 1
    agg = DailyReportAggregate.objects.get(tenant=tenant, date=yesterday)
    assert agg.appointments_total == 1
    assert agg.revenue_total == Decimal("50")


@pytest.mark.django_db
def test_backfill_no_appointments_returns_none():
    tenant = _make_tenant()
    from reports.backfill import backfill_tenant
    result = backfill_tenant(tenant.id)
    assert result is None
    assert not DailyReportAggregate.objects.filter(tenant=tenant).exists()


@pytest.mark.django_db
def test_run_backfill_covers_all_active_tenants():
    t1 = _make_tenant()
    t2 = _make_tenant()
    u1 = _make_user(t1)
    u2 = _make_user(t2)
    yesterday = date.today() - timedelta(days=1)

    _make_appointment(t1, u1, day=yesterday, status="completed")
    _make_appointment(t2, u2, day=yesterday, status="completed")

    from reports.backfill import run_backfill
    run_backfill(since=yesterday, until=yesterday)

    assert DailyReportAggregate.objects.filter(tenant=t1, date=yesterday).exists()
    assert DailyReportAggregate.objects.filter(tenant=t2, date=yesterday).exists()


# ── Daily update task tests ───────────────────────────────────────────────────


@pytest.mark.django_db
def test_update_daily_aggregates_task_covers_yesterday():
    tenant = _make_tenant()
    user = _make_user(tenant)
    yesterday = date.today() - timedelta(days=1)

    _make_appointment(tenant, user, day=yesterday, status="completed", price=Decimal("200"))

    from reports.tasks import update_daily_aggregates
    update_daily_aggregates()

    agg = DailyReportAggregate.objects.get(tenant=tenant, date=yesterday)
    assert agg.appointments_completed == 1
    assert agg.revenue_total == Decimal("200")


@pytest.mark.django_db
def test_update_daily_aggregates_does_not_touch_older_days():
    tenant = _make_tenant()
    user = _make_user(tenant)
    two_days_ago = date.today() - timedelta(days=2)

    # pre-existing aggregate for two days ago with wrong data
    DailyReportAggregate.objects.create(
        tenant=tenant, date=two_days_ago,
        appointments_total=5, appointments_completed=5, revenue_total=Decimal("500"),
    )

    from reports.tasks import update_daily_aggregates
    update_daily_aggregates()

    # Two-days-ago aggregate should be untouched
    agg = DailyReportAggregate.objects.get(tenant=tenant, date=two_days_ago)
    assert agg.appointments_total == 5


# ── Aggregator fallback tests ─────────────────────────────────────────────────


@pytest.mark.django_db
def test_get_overview_data_uses_aggregates_when_covered():
    tenant = _make_tenant()
    yesterday = date.today() - timedelta(days=1)
    two_days_ago = date.today() - timedelta(days=2)

    DailyReportAggregate.objects.create(
        tenant=tenant, date=yesterday,
        appointments_total=10, appointments_completed=8, revenue_total=Decimal("400"),
    )
    DailyReportAggregate.objects.create(
        tenant=tenant, date=two_days_ago,
        appointments_total=5, appointments_completed=3, revenue_total=Decimal("150"),
    )

    start = timezone.make_aware(
        timezone.datetime(two_days_ago.year, two_days_ago.month, two_days_ago.day)
    )
    end = timezone.make_aware(
        timezone.datetime(yesterday.year, yesterday.month, yesterday.day, 23, 59, 59)
    )

    from reports.aggregator import get_overview_data
    data = get_overview_data(tenant.id, start, end)

    assert data["appointments_total"] == 15
    assert data["appointments_completed"] == 11
    assert data["revenue_total"] == Decimal("550")


@pytest.mark.django_db
def test_get_overview_data_fallback_when_gap_in_coverage():
    tenant = _make_tenant()
    user = _make_user(tenant)
    yesterday = date.today() - timedelta(days=1)
    two_days_ago = date.today() - timedelta(days=2)

    # Only one day covered (two_days_ago missing)
    DailyReportAggregate.objects.create(
        tenant=tenant, date=yesterday,
        appointments_total=99, appointments_completed=99, revenue_total=Decimal("9999"),
    )
    _make_appointment(tenant, user, day=two_days_ago, status="completed", price=Decimal("60"))

    start = timezone.make_aware(
        timezone.datetime(two_days_ago.year, two_days_ago.month, two_days_ago.day)
    )
    end = timezone.make_aware(
        timezone.datetime(yesterday.year, yesterday.month, yesterday.day, 23, 59, 59)
    )

    from reports.aggregator import get_overview_data
    data = get_overview_data(tenant.id, start, end)

    # Should use live query (1 real appointment), not the corrupt aggregate
    assert data["appointments_total"] == 1
    assert data["appointments_completed"] == 1
    assert data["revenue_total"] == Decimal("60")


@pytest.mark.django_db
def test_get_revenue_series_uses_aggregates_when_covered():
    tenant = _make_tenant()
    yesterday = date.today() - timedelta(days=1)
    two_days_ago = date.today() - timedelta(days=2)

    DailyReportAggregate.objects.create(
        tenant=tenant, date=yesterday,
        appointments_total=4, appointments_completed=3, revenue_total=Decimal("120"),
    )
    DailyReportAggregate.objects.create(
        tenant=tenant, date=two_days_ago,
        appointments_total=2, appointments_completed=2, revenue_total=Decimal("80"),
    )

    start = timezone.make_aware(
        timezone.datetime(two_days_ago.year, two_days_ago.month, two_days_ago.day)
    )
    end = timezone.make_aware(
        timezone.datetime(yesterday.year, yesterday.month, yesterday.day, 23, 59, 59)
    )

    from reports.aggregator import get_revenue_series
    rows = get_revenue_series(tenant.id, start, end, interval="day")

    assert len(rows) == 2
    assert rows[0]["appointment_count"] == 2
    assert rows[0]["revenue"] == Decimal("80")
    assert rows[1]["appointment_count"] == 3
    assert rows[1]["revenue"] == Decimal("120")


@pytest.mark.django_db
def test_get_revenue_series_fallback_when_no_aggregates():
    tenant = _make_tenant()
    user = _make_user(tenant)
    yesterday = date.today() - timedelta(days=1)

    _make_appointment(tenant, user, day=yesterday, status="completed", price=Decimal("75"))

    start = timezone.make_aware(
        timezone.datetime(yesterday.year, yesterday.month, yesterday.day)
    )
    end = timezone.make_aware(
        timezone.datetime(yesterday.year, yesterday.month, yesterday.day, 23, 59, 59)
    )

    from reports.aggregator import get_revenue_series
    rows = get_revenue_series(tenant.id, start, end, interval="day")

    assert len(rows) == 1
    assert rows[0]["appointment_count"] == 1
    assert rows[0]["revenue"] == Decimal("75")


# ── API endpoint integration tests ────────────────────────────────────────────


@pytest.mark.django_db
@override_settings(CACHES=_NO_CACHE)
def test_overview_endpoint_uses_aggregate_path():
    tenant = _make_tenant()
    user = _make_user(tenant)
    yesterday = date.today() - timedelta(days=1)

    DailyReportAggregate.objects.create(
        tenant=tenant, date=yesterday,
        appointments_total=20, appointments_completed=15, revenue_total=Decimal("750"),
    )

    r = _client(user).get(
        "/api/reports/overview/",
        {"from": f"{yesterday}T00:00:00", "to": f"{yesterday}T23:59:59"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["appointments_total"] == 20
    assert body["appointments_completed"] == 15
    assert float(body["revenue_total"]) == pytest.approx(750.0)


@pytest.mark.django_db
@override_settings(CACHES=_NO_CACHE)
def test_overview_endpoint_fallback_returns_correct_live_data():
    tenant = _make_tenant()
    user = _make_user(tenant)
    yesterday = date.today() - timedelta(days=1)

    _make_appointment(tenant, user, day=yesterday, status="completed", price=Decimal("100"))
    _make_appointment(tenant, user, day=yesterday, status="cancelled", price=Decimal("50"))

    r = _client(user).get(
        "/api/reports/overview/",
        {"from": f"{yesterday}T00:00:00", "to": f"{yesterday}T23:59:59"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["appointments_total"] == 2
    assert body["appointments_completed"] == 1
    assert float(body["revenue_total"]) == pytest.approx(100.0)


@pytest.mark.django_db
@override_settings(CACHES=_NO_CACHE)
def test_revenue_endpoint_uses_aggregate_path():
    tenant = _make_tenant()
    user = _make_user(tenant)
    yesterday = date.today() - timedelta(days=1)

    DailyReportAggregate.objects.create(
        tenant=tenant, date=yesterday,
        appointments_total=5, appointments_completed=4, revenue_total=Decimal("200"),
    )

    r = _client(user).get(
        "/api/reports/revenue/",
        {"from": f"{yesterday}T00:00:00", "to": f"{yesterday}T23:59:59", "interval": "day"},
    )
    assert r.status_code == 200
    body = r.json()
    series = body["series"]
    assert len(series) == 1
    assert series[0]["appointment_count"] == 4
    assert float(series[0]["revenue"]) == pytest.approx(200.0)
