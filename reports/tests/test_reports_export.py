import pytest
from django.utils import timezone
from rest_framework.test import APIClient
from django.http import HttpResponse
from typing import cast
import csv
import io
import re
import uuid
from decimal import Decimal
from django.contrib.auth import get_user_model
from users.models import UserFeatureFlags, Tenant
from django.test import override_settings
from django.core.cache import cache
from core.models import Appointment, Professional, SalonCustomer, ScheduleSlot, Service

User = get_user_model()


def _create_tenant_user(*, username_prefix: str):
    suffix = str(uuid.uuid4())[:8]
    tenant = Tenant.objects.create(
        slug=f"{username_prefix}-tenant-{suffix}",
        name=f"{username_prefix.title()} Tenant {suffix}",
        plan_tier=Tenant.PLAN_PRO,
        reports_enabled=True,
    )
    user = User.objects.create_user(
        username=f"{username_prefix}_{suffix}",
        email=f"{username_prefix}_{suffix}@test.com",
        password="x",
        tenant=tenant,
    )
    UserFeatureFlags.objects.update_or_create(
        user=user,
        defaults={"is_pro": True, "reports_enabled": True},
    )
    return tenant, user


def _create_completed_appointment_for_tenant(*, tenant, user, service_name: str):
    now = timezone.now()
    service = Service.objects.create(
        tenant=tenant,
        user=user,
        name=service_name,
        duration_minutes=30,
        price_eur=Decimal("100.00"),
    )
    professional = Professional.objects.create(
        tenant=tenant,
        user=user,
        name=f"Prof {service_name}",
    )
    customer = SalonCustomer.objects.create(
        tenant=tenant,
        name=f"Customer {service_name}",
        email=f"{service_name.lower().replace(' ', '_')}_{uuid.uuid4().hex[:6]}@test.com",
    )
    slot = ScheduleSlot.objects.create(
        tenant=tenant,
        professional=professional,
        start_time=now,
        end_time=now + timezone.timedelta(minutes=30),
        is_available=False,
        status="booked",
    )
    return Appointment.objects.create(
        tenant=tenant,
        client=user,
        customer=customer,
        service=service,
        professional=professional,
        slot=slot,
        status="completed",
    )


def _count_date_rows(csv_body: str) -> int:
    reader = csv.reader(io.StringIO(csv_body))
    pattern = re.compile(r"^\d{2}/\d{2}/\d{4}$")
    return sum(1 for row in reader if row and pattern.match((row[0] or "").strip()))


@pytest.mark.django_db
def test_export_overview_csv_ok_without_data():
    # usuário PRO com módulo habilitado
    u = User.objects.create_user(username="csvuser", email="csv@e.com", password="x")
    UserFeatureFlags.objects.update_or_create(
        user=u, defaults={"is_pro": True, "reports_enabled": True}
    )

    c = APIClient()
    c.force_authenticate(u)

    now = timezone.now()
    start = (now - timezone.timedelta(days=7)).date().isoformat()
    end = now.date().isoformat()

    r = c.get(f"/api/reports/overview/export/?from={start}&to={end}")
    r = cast(HttpResponse, r)
    assert r.status_code == 200
    # content-type
    assert r["Content-Type"].startswith("text/csv")
    # conteúdo básico
    body = r.content.decode("utf-8")
    assert "TimelyOne" in body  # Novo cabeçalho
    assert "Agendamentos Totais" in body  # Coluna traduzida
    assert "data,receita" in body.replace(" ", "").lower() or "Data,Receita" in body


@pytest.mark.django_db
@override_settings(
    CACHES={
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": "throttle-tests-overview",
        }
    },
    REST_FRAMEWORK={
        "DEFAULT_AUTHENTICATION_CLASSES": [
            "rest_framework_simplejwt.authentication.JWTAuthentication",
        ],
        "DEFAULT_PERMISSION_CLASSES": [
            "rest_framework.permissions.IsAuthenticated",
        ],
        "DEFAULT_THROTTLE_CLASSES": [
            "rest_framework.throttling.UserRateThrottle",
            "rest_framework.throttling.ScopedRateThrottle",
        ],
        "DEFAULT_THROTTLE_RATES": {
            "user": "1000/day",
            "reports": "60/min",
            "export_csv": "2/min",  # mais baixo para testar rapidamente
        },
    },
)
def test_export_overview_csv_throttled():
    cache.clear()
    u = User.objects.create_user(
        username="csvlimit", email="csvlimit@e.com", password="x"
    )
    UserFeatureFlags.objects.update_or_create(
        user=u, defaults={"is_pro": True, "reports_enabled": True}
    )

    c = APIClient()
    c.force_authenticate(u)

    now = timezone.now()
    start = (now - timezone.timedelta(days=7)).date().isoformat()
    end = now.date().isoformat()
    url = f"/api/reports/overview/export/?from={start}&to={end}"

    # duas requisições OK
    assert c.get(url).status_code == 200
    assert c.get(url).status_code == 200
    # terceira deve estourar o throttle
    r3 = c.get(url)
    assert r3.status_code in (429, 403)  # 429 esperado; 403 se algum guard falhar


@pytest.mark.django_db
def test_export_top_services_csv_ok_without_data():
    u = User.objects.create_user(
        username="csv_top", email="csv_top@e.com", password="x"
    )
    UserFeatureFlags.objects.update_or_create(
        user=u, defaults={"is_pro": True, "reports_enabled": True}
    )
    c = APIClient()
    c.force_authenticate(u)

    now = timezone.now()
    start = (now - timezone.timedelta(days=7)).date().isoformat()
    end = now.date().isoformat()

    r = c.get(f"/api/reports/top-services/export/?from={start}&to={end}")
    r = cast(HttpResponse, r)
    assert r.status_code == 200
    assert r["Content-Type"].startswith("text/csv")


@pytest.mark.django_db
@override_settings(
    CACHES={
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": "throttle-tests-overview",
        }
    },
    REST_FRAMEWORK={
        "DEFAULT_AUTHENTICATION_CLASSES": [
            "rest_framework_simplejwt.authentication.JWTAuthentication",
        ],
        "DEFAULT_PERMISSION_CLASSES": [
            "rest_framework.permissions.IsAuthenticated",
        ],
        "DEFAULT_THROTTLE_CLASSES": [
            "rest_framework.throttling.UserRateThrottle",
            "rest_framework.throttling.ScopedRateThrottle",
        ],
        "DEFAULT_THROTTLE_RATES": {
            "user": "1000/day",
            "reports": "60/min",
            "export_csv": "2/min",  # baixo para testar
        },
    },
)
def test_export_top_services_csv_throttled():
    cache.clear()
    u = User.objects.create_user(username="csv_top_thr", email="ct@e.com", password="x")
    UserFeatureFlags.objects.update_or_create(
        user=u, defaults={"is_pro": True, "reports_enabled": True}
    )
    c = APIClient()
    c.force_authenticate(u)

    now = timezone.now()
    start = (now - timezone.timedelta(days=7)).date().isoformat()
    end = now.date().isoformat()
    url = f"/api/reports/top-services/export/?from={start}&to={end}"

    assert c.get(url).status_code == 200
    assert c.get(url).status_code == 200
    assert c.get(url).status_code == 429


@pytest.mark.django_db
def test_export_revenue_csv_ok_without_data():
    u = User.objects.create_user(
        username="csv_rev", email="csv_rev@e.com", password="x"
    )
    UserFeatureFlags.objects.update_or_create(
        user=u, defaults={"is_pro": True, "reports_enabled": True}
    )
    c = APIClient()
    c.force_authenticate(u)

    now = timezone.now()
    start = (now - timezone.timedelta(days=7)).date().isoformat()
    end = now.date().isoformat()

    r = c.get(f"/api/reports/revenue/export/?from={start}&to={end}&interval=day")
    r = cast(HttpResponse, r)
    assert r.status_code == 200
    assert r["Content-Type"].startswith("text/csv")


@pytest.mark.django_db
@override_settings(
    CACHES={
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": "throttle-tests-overview",
        }
    },
    REST_FRAMEWORK={
        "DEFAULT_AUTHENTICATION_CLASSES": [
            "rest_framework_simplejwt.authentication.JWTAuthentication",
        ],
        "DEFAULT_PERMISSION_CLASSES": [
            "rest_framework.permissions.IsAuthenticated",
        ],
        "DEFAULT_THROTTLE_CLASSES": [
            "rest_framework.throttling.UserRateThrottle",
            "rest_framework.throttling.ScopedRateThrottle",
        ],
        "DEFAULT_THROTTLE_RATES": {
            "user": "1000/day",
            "reports": "60/min",
            "export_csv": "2/min",
        },
    },
)
def test_export_revenue_csv_throttled():
    cache.clear()
    u = User.objects.create_user(
        username="csv_rev_thr", email="crt@e.com", password="x"
    )
    UserFeatureFlags.objects.update_or_create(
        user=u, defaults={"is_pro": True, "reports_enabled": True}
    )
    c = APIClient()
    c.force_authenticate(u)

    now = timezone.now()
    start = (now - timezone.timedelta(days=7)).date().isoformat()
    end = now.date().isoformat()
    url = f"/api/reports/revenue/export/?from={start}&to={end}&interval=week"

    assert c.get(url).status_code == 200
    assert c.get(url).status_code == 200
    assert c.get(url).status_code == 429


@pytest.mark.django_db
def test_export_top_services_csv_tenant_isolation():
    tenant_a, user_a = _create_tenant_user(username_prefix="csv_top_a")
    tenant_b, user_b = _create_tenant_user(username_prefix="csv_top_b")

    _create_completed_appointment_for_tenant(
        tenant=tenant_a, user=user_a, service_name="ServicoTenantA"
    )
    _create_completed_appointment_for_tenant(
        tenant=tenant_b, user=user_b, service_name="ServicoTenantB"
    )

    c = APIClient()
    c.force_authenticate(user_a)

    now = timezone.now()
    start = (now - timezone.timedelta(days=7)).date().isoformat()
    end = (now + timezone.timedelta(days=1)).date().isoformat()

    r = c.get(f"/api/reports/top-services/export/?from={start}&to={end}")
    assert r.status_code == 200
    body = r.content.decode("utf-8")
    assert "ServicoTenantA" in body
    assert "ServicoTenantB" not in body


@pytest.mark.django_db
def test_export_revenue_csv_tenant_isolation():
    tenant_a, user_a = _create_tenant_user(username_prefix="csv_rev_a")
    tenant_b, user_b = _create_tenant_user(username_prefix="csv_rev_b")

    _create_completed_appointment_for_tenant(
        tenant=tenant_a, user=user_a, service_name="ServicoRevenueA"
    )
    appt_b = _create_completed_appointment_for_tenant(
        tenant=tenant_b, user=user_b, service_name="ServicoRevenueB"
    )

    # Se houver vazamento entre tenants, teremos 2 buckets de data no CSV.
    Appointment.objects.filter(id=appt_b.id).update(
        created_at=timezone.now() - timezone.timedelta(days=2)
    )

    c = APIClient()
    c.force_authenticate(user_a)

    now = timezone.now()
    start = (now - timezone.timedelta(days=7)).date().isoformat()
    end = (now + timezone.timedelta(days=1)).date().isoformat()

    r = c.get(f"/api/reports/revenue/export/?from={start}&to={end}&interval=day")
    assert r.status_code == 200
    body = r.content.decode("utf-8")
    assert _count_date_rows(body) == 1


@pytest.mark.django_db
def test_export_basic_reports_csv_tenant_isolation():
    tenant_a, user_a = _create_tenant_user(username_prefix="csv_basic_a")
    tenant_b, user_b = _create_tenant_user(username_prefix="csv_basic_b")

    _create_completed_appointment_for_tenant(
        tenant=tenant_a, user=user_a, service_name="ServicoBasicA"
    )
    _create_completed_appointment_for_tenant(
        tenant=tenant_b, user=user_b, service_name="ServicoBasicB"
    )

    c = APIClient()
    c.force_authenticate(user_a)

    now = timezone.now()
    start = (now - timezone.timedelta(days=7)).date().isoformat()
    end = (now + timezone.timedelta(days=1)).date().isoformat()

    r = c.get(f"/api/reports/basic/export/?from={start}&to={end}")
    assert r.status_code == 200

    body = r.content.decode("utf-8")
    reader = csv.reader(io.StringIO(body))
    summary_rows = [row for row in reader if len(row) >= 2 and row[0].isdigit()]
    assert summary_rows
    # appointments_total e appointments_completed devem refletir só o tenant autenticado
    assert summary_rows[0][0] == "1"
    assert summary_rows[0][1] == "1"


@pytest.mark.django_db
def test_export_advanced_reports_csv_tenant_isolation():
    tenant_a, user_a = _create_tenant_user(username_prefix="csv_adv_a")
    tenant_b, user_b = _create_tenant_user(username_prefix="csv_adv_b")

    _create_completed_appointment_for_tenant(
        tenant=tenant_a, user=user_a, service_name="ServicoAdvancedA"
    )
    _create_completed_appointment_for_tenant(
        tenant=tenant_b, user=user_b, service_name="ServicoAdvancedB"
    )

    c = APIClient()
    c.force_authenticate(user_a)

    now = timezone.now()
    start = (now - timezone.timedelta(days=7)).date().isoformat()
    end = (now + timezone.timedelta(days=1)).date().isoformat()

    r = c.get(f"/api/reports/advanced/export/?from={start}&to={end}&interval=day")
    assert r.status_code == 200
    body = r.content.decode("utf-8")
    assert "ServicoAdvancedA" in body
    assert "ServicoAdvancedB" not in body
