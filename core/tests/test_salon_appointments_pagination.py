import pytest
from datetime import timedelta
from django.utils import timezone
from rest_framework.test import APIClient

from users.models import CustomUser, Tenant
from core.models import Service, Professional, ScheduleSlot, Appointment


def _create_apt(user, service, professional, start_dt, note_prefix="Apt"):
    end_dt = start_dt + timedelta(minutes=service.duration_minutes)
    slot = ScheduleSlot.objects.create(
        professional=professional,
        start_time=start_dt,
        end_time=end_dt,
        is_available=False,
    )
    return Appointment.objects.create(
        client=user,
        service=service,
        professional=professional,
        slot=slot,
        notes=f"{note_prefix} {start_dt.isoformat()}",
    )


@pytest.mark.django_db
def test_default_pagination_headers(user_fixture):
    client = APIClient()
    client.force_authenticate(user=user_fixture)

    svc = Service.objects.create(
        user=user_fixture, name="Corte", duration_minutes=30, price_eur="20.00"
    )
    prof = Professional.objects.create(user=user_fixture, name="Pro", bio="OK")

    now = timezone.now()
    # cria 25 agendamentos
    for i in range(25):
        _create_apt(user_fixture, svc, prof, now + timedelta(minutes=i))

    resp = client.get("/api/salon/appointments/")
    assert resp.status_code == 200
    # default: limit=20, offset=0
    assert isinstance(resp.data, list)
    assert len(resp.data) == 20

    assert resp["X-Total-Count"] == "25"
    assert resp["X-Limit"] == "20"
    assert resp["X-Offset"] == "0"

    link = resp.get("Link", "")
    assert "rel=\"next\"" in link
    assert "rel=\"prev\"" not in link


@pytest.mark.django_db
def test_limit_capped_to_100(user_fixture):
    client = APIClient()
    client.force_authenticate(user=user_fixture)

    svc = Service.objects.create(
        user=user_fixture, name="Corte", duration_minutes=30, price_eur="20.00"
    )
    prof = Professional.objects.create(user=user_fixture, name="Pro", bio="OK")

    now = timezone.now()
    # cria 110 agendamentos
    for i in range(110):
        _create_apt(user_fixture, svc, prof, now + timedelta(minutes=i))

    resp = client.get("/api/salon/appointments/", {"limit": 500})
    assert resp.status_code == 200
    assert len(resp.data) == 100
    assert resp["X-Limit"] == "100"
    assert resp["X-Total-Count"] == "110"

    link = resp.get("Link", "")
    # como total=110 e limit=100, deve existir next para offset=100
    assert "rel=\"next\"" in link
    assert "offset=100" in link


@pytest.mark.django_db
def test_offset_invalid_returns_400(user_fixture):
    client = APIClient()
    client.force_authenticate(user=user_fixture)

    resp = client.get("/api/salon/appointments/", {"offset": "xyz"})
    assert resp.status_code == 400
    # nossas respostas de erro são envelopadas em { error: { details: {...} } }
    assert "error" in resp.data
    assert "details" in resp.data["error"]
    assert "offset" in resp.data["error"]["details"]


@pytest.mark.django_db
def test_ordering_by_start_time(user_fixture):
    client = APIClient()
    client.force_authenticate(user=user_fixture)

    svc = Service.objects.create(
        user=user_fixture, name="Corte", duration_minutes=30, price_eur="20.00"
    )
    prof = Professional.objects.create(user=user_fixture, name="Pro", bio="OK")

    now = timezone.now()
    a1 = _create_apt(user_fixture, svc, prof, now + timedelta(hours=1), note_prefix="A1")
    a2 = _create_apt(user_fixture, svc, prof, now + timedelta(hours=2), note_prefix="A2")
    a3 = _create_apt(user_fixture, svc, prof, now + timedelta(hours=3), note_prefix="A3")

    # asc: primeiro é A1
    resp_asc = client.get("/api/salon/appointments/", {"ordering": "start_time"})
    assert resp_asc.status_code == 200
    assert resp_asc.data[0]["id"] == a1.id
    assert resp_asc.data[-1]["id"] == a3.id

    # desc: primeiro é A3
    resp_desc = client.get("/api/salon/appointments/", {"ordering": "-start_time"})
    assert resp_desc.status_code == 200
    assert resp_desc.data[0]["id"] == a3.id
    assert resp_desc.data[-1]["id"] == a1.id


@pytest.mark.django_db
def test_tenant_scope_reflected_in_total_count(user_fixture):
    client = APIClient()
    client.force_authenticate(user=user_fixture)

    # owner salon
    svc = Service.objects.create(
        user=user_fixture, name="Corte", duration_minutes=30, price_eur="20.00"
    )
    prof = Professional.objects.create(user=user_fixture, name="Pro", bio="OK")

    # other salon
    other = CustomUser.objects.create_user(
        username="other", email="other@example.com", password="pass"
    )
    other_tenant = Tenant.objects.create(name="Tenant Pagination", slug="tenant-pagination")
    other.tenant = other_tenant
    other.save(update_fields=["tenant"])

    svc_o = Service.objects.create(
        tenant=other_tenant,
        user=other,
        name="Barba",
        duration_minutes=20,
        price_eur="10.00",
    )
    prof_o = Professional.objects.create(tenant=other_tenant, user=other, name="Outro", bio="Pro")

    now = timezone.now()
    # cria 10 para owner
    for i in range(10):
        _create_apt(user_fixture, svc, prof, now + timedelta(minutes=i), note_prefix="Own")
    # cria 5 para other
    for i in range(5):
        _create_apt(other, svc_o, prof_o, now + timedelta(minutes=60 + i), note_prefix="Other")

    # Em ambiente de teste o isolamento por tenant está desligado pelo mixin,
    # então o OWNER deve ver o total agregado (10 do owner + 5 do other = 15)
    client_owner = APIClient()
    client_owner.force_authenticate(user=user_fixture)

    resp_owner = client_owner.get("/api/salon/appointments/")
    assert resp_owner.status_code == 200
    assert resp_owner["X-Total-Count"] == "15"
    assert len(resp_owner.data) == min(15, int(resp_owner["X-Limit"]))


@pytest.mark.django_db
def test_link_headers_next_and_prev(user_fixture):
    client = APIClient()
    client.force_authenticate(user=user_fixture)

    svc = Service.objects.create(
        user=user_fixture, name="Corte", duration_minutes=30, price_eur="20.00"
    )
    prof = Professional.objects.create(user=user_fixture, name="Pro", bio="OK")

    now = timezone.now()
    # cria 25 agendamentos
    for i in range(25):
        _create_apt(user_fixture, svc, prof, now + timedelta(minutes=i))

    # pedir segunda página (offset=10, limit=10)
    resp = client.get("/api/salon/appointments/", {"limit": 10, "offset": 10})
    assert resp.status_code == 200
    assert len(resp.data) == 10

    link = resp.get("Link", "")
    assert "rel=\"next\"" in link
    assert "rel=\"prev\"" in link
    # next deve apontar para offset=20 e prev para offset=0
    assert "offset=20" in link
    assert "offset=0" in link