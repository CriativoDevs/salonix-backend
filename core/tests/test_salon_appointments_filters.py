import pytest
from datetime import timedelta
from django.utils import timezone
from rest_framework.test import APIClient

from users.models import CustomUser
from core.models import Service, Professional, ScheduleSlot, Appointment


@pytest.mark.django_db
def test_filter_by_status_and_visibility(user_fixture):
    client = APIClient()
    client.force_authenticate(user=user_fixture)

    # outro salão
    other = CustomUser.objects.create_user(
        username="other", email="other@example.com", password="pass"
    )

    # recursos do salão logado
    svc = Service.objects.create(
        user=user_fixture, name="Corte", duration_minutes=30, price_eur="10.00"
    )
    prof = Professional.objects.create(user=user_fixture, name="Lucas", bio="Top")
    now = timezone.now()
    s1 = ScheduleSlot.objects.create(
        professional=prof,
        start_time=now + timedelta(days=1),
        end_time=now + timedelta(days=1, minutes=30),
        is_available=False,
    )
    s2 = ScheduleSlot.objects.create(
        professional=prof,
        start_time=now + timedelta(days=2),
        end_time=now + timedelta(days=2, minutes=30),
        is_available=False,
    )

    a1 = Appointment.objects.create(
        client=user_fixture, service=svc, professional=prof, slot=s1, status="scheduled"
    )
    a2 = Appointment.objects.create(
        client=user_fixture, service=svc, professional=prof, slot=s2, status="cancelled"
    )

    # recursos de outro salão (não devem aparecer)
    svc_o = Service.objects.create(
        user=other, name="Barba", duration_minutes=20, price_eur="8.00"
    )
    prof_o = Professional.objects.create(user=other, name="João", bio="Pro")
    s_o = ScheduleSlot.objects.create(
        professional=prof_o,
        start_time=now + timedelta(days=1),
        end_time=now + timedelta(days=1, minutes=20),
        is_available=False,
    )
    Appointment.objects.create(
        client=other, service=svc_o, professional=prof_o, slot=s_o, status="scheduled"
    )

    # filtra scheduled
    resp = client.get("/api/salon/appointments/", {"status": "scheduled"})
    assert resp.status_code == 200
    ids = {item["id"] for item in resp.data}
    assert a1.id in ids
    assert a2.id not in ids
    # garante que não vazou dados do outro salão
    assert len(ids) == 1


@pytest.mark.django_db
def test_filter_by_date_range(user_fixture):
    client = APIClient()
    client.force_authenticate(user=user_fixture)

    svc = Service.objects.create(
        user=user_fixture, name="Corte", duration_minutes=30, price_eur="10.00"
    )
    prof = Professional.objects.create(user=user_fixture, name="Lucas", bio="Top")
    now = timezone.now()

    s1 = ScheduleSlot.objects.create(
        professional=prof,
        start_time=now + timedelta(days=1),
        end_time=now + timedelta(days=1, minutes=30),
        is_available=False,
    )
    s2 = ScheduleSlot.objects.create(
        professional=prof,
        start_time=now + timedelta(days=3),
        end_time=now + timedelta(days=3, minutes=30),
        is_available=False,
    )
    s3 = ScheduleSlot.objects.create(
        professional=prof,
        start_time=now + timedelta(days=5),
        end_time=now + timedelta(days=5, minutes=30),
        is_available=False,
    )

    a1 = Appointment.objects.create(
        client=user_fixture, service=svc, professional=prof, slot=s1
    )
    a2 = Appointment.objects.create(
        client=user_fixture, service=svc, professional=prof, slot=s2
    )
    Appointment.objects.create(
        client=user_fixture, service=svc, professional=prof, slot=s3
    )

    # pega do dia +2 até +4 -> deve retornar apenas a2 (slot no dia +3)
    date_from = (now + timedelta(days=2)).date().isoformat()
    date_to = (now + timedelta(days=4)).date().isoformat()

    resp = client.get(
        "/api/salon/appointments/", {"date_from": date_from, "date_to": date_to}
    )
    assert resp.status_code == 200
    ids = {item["id"] for item in resp.data}
    assert a2.id in ids
    assert a1.id not in ids
    assert len(ids) == 1


@pytest.mark.django_db
def test_filter_by_professional_and_service(user_fixture):
    client = APIClient()
    client.force_authenticate(user=user_fixture)

    svc1 = Service.objects.create(
        user=user_fixture, name="Corte", duration_minutes=30, price_eur="10.00"
    )
    svc2 = Service.objects.create(
        user=user_fixture, name="Barba", duration_minutes=20, price_eur="8.00"
    )

    prof1 = Professional.objects.create(user=user_fixture, name="Lucas", bio="Top")
    prof2 = Professional.objects.create(user=user_fixture, name="João", bio="Pro")

    now = timezone.now()

    s1 = ScheduleSlot.objects.create(
        professional=prof1,
        start_time=now + timedelta(days=1),
        end_time=now + timedelta(days=1, minutes=30),
        is_available=False,
    )
    s2 = ScheduleSlot.objects.create(
        professional=prof2,
        start_time=now + timedelta(days=2),
        end_time=now + timedelta(days=2, minutes=20),
        is_available=False,
    )

    a1 = Appointment.objects.create(
        client=user_fixture, service=svc1, professional=prof1, slot=s1
    )
    Appointment.objects.create(
        client=user_fixture, service=svc2, professional=prof2, slot=s2
    )

    # filtra por professional_id + service_id -> deve trazer só a1
    resp = client.get(
        "/api/salon/appointments/",
        {"professional_id": str(prof1.id), "service_id": str(svc1.id)},
    )
    assert resp.status_code == 200
    ids = {item["id"] for item in resp.data}
    assert a1.id in ids
    assert len(ids) == 1
