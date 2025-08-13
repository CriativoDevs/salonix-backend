# core/tests/test_appointment_detail.py
import pytest
from django.utils import timezone
from datetime import timedelta
from rest_framework.test import APIClient

from users.models import CustomUser
from core.models import Service, Professional, ScheduleSlot, Appointment


@pytest.mark.django_db
def test_get_appointment_detail_as_client(user_fixture):
    client = APIClient()
    client.force_authenticate(user=user_fixture)

    # salão (owner)
    salon_owner = user_fixture  # reaproveitamos o mesmo usuário como dono
    service = Service.objects.create(
        user=salon_owner, name="Corte", duration_minutes=30, price_eur="20.00"
    )
    professional = Professional.objects.create(
        user=salon_owner, name="Lucas", bio="Top", is_active=True
    )
    slot = ScheduleSlot.objects.create(
        professional=professional,
        start_time=timezone.now() + timedelta(days=1),
        end_time=timezone.now() + timedelta(days=1, minutes=30),
        is_available=False,
        status="booked",
    )
    appt = Appointment.objects.create(
        client=user_fixture,
        service=service,
        professional=professional,
        slot=slot,
        notes="Detalhe!",
    )

    resp = client.get(f"/api/appointments/{appt.id}/")
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == appt.id
    assert data["service"]["name"] == "Corte"
    assert data["professional"]["name"] == "Lucas"
    assert data["slot"]["status"] == "booked"
    assert data["client_username"] == user_fixture.username


@pytest.mark.django_db
def test_get_appointment_detail_as_salon_owner(user_fixture):
    # usuário A = dono do salão
    salon_owner = user_fixture
    client_user = CustomUser.objects.create_user(
        username="cliente", password="x", email="cliente@test.com"
    )

    api = APIClient()
    api.force_authenticate(user=salon_owner)

    service = Service.objects.create(
        user=salon_owner, name="Barba", duration_minutes=20, price_eur="10.00"
    )
    professional = Professional.objects.create(
        user=salon_owner, name="João", bio="", is_active=True
    )
    slot = ScheduleSlot.objects.create(
        professional=professional,
        start_time=timezone.now() + timedelta(days=2),
        end_time=timezone.now() + timedelta(days=2, minutes=20),
        is_available=False,
        status="booked",
    )
    appt = Appointment.objects.create(
        client=client_user,
        service=service,
        professional=professional,
        slot=slot,
        notes="Teste",
    )

    resp = api.get(f"/api/appointments/{appt.id}/")
    assert resp.status_code == 200
    body = resp.json()
    assert body["service"]["name"] == "Barba"
    assert body["professional"]["name"] == "João"


@pytest.mark.django_db
def test_get_appointment_detail_forbidden_for_third_party(user_fixture):
    # dono do salão
    owner = user_fixture
    # cliente do agendamento
    client_user = CustomUser.objects.create_user(
        username="cliente2", password="x", email="c2@test.com"
    )
    # terceiro, sem relação
    outsider = CustomUser.objects.create_user(
        username="outsider", password="x", email="out@test.com"
    )

    service = Service.objects.create(
        user=owner, name="Sobrancelha", duration_minutes=15, price_eur="8.00"
    )
    professional = Professional.objects.create(
        user=owner, name="Mara", bio="", is_active=True
    )
    slot = ScheduleSlot.objects.create(
        professional=professional,
        start_time=timezone.now() + timedelta(days=3),
        end_time=timezone.now() + timedelta(days=3, minutes=15),
        is_available=False,
        status="booked",
    )
    appt = Appointment.objects.create(
        client=client_user,
        service=service,
        professional=professional,
        slot=slot,
        notes="Privado",
    )

    api = APIClient()
    api.force_authenticate(user=outsider)
    resp = api.get(f"/api/appointments/{appt.id}/")
    # 404 para não vazar existência do recurso
    assert resp.status_code == 404
