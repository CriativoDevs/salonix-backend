import pytest
from datetime import timedelta
from django.utils import timezone
from rest_framework.test import APIClient

from users.models import CustomUser
from core.models import Service, Professional, ScheduleSlot, Appointment


@pytest.mark.django_db
def test_me_appointments_requires_auth():
    client = APIClient()
    resp = client.get("/api/me/appointments/")
    assert resp.status_code == 401


@pytest.mark.django_db
def test_me_appointments_lists_only_current_user(user_fixture):
    client = APIClient()
    client.force_authenticate(user=user_fixture)

    # Setup básico: serviço e profissional (do salão do user_fixture)
    service = Service.objects.create(
        user=user_fixture, name="Corte", duration_minutes=30, price_eur="20.00"
    )
    pro = Professional.objects.create(
        user=user_fixture, name="Lucas", bio="Top", is_active=True
    )

    now = timezone.now()
    # Slot 1 (do usuário autenticado)
    slot1 = ScheduleSlot.objects.create(
        professional=pro,
        start_time=now + timedelta(days=1),
        end_time=now + timedelta(days=1, minutes=30),
        is_available=False,
    )
    Appointment.objects.create(
        client=user_fixture,
        service=service,
        professional=pro,
        slot=slot1,
        notes="Meu agendamento",
    )

    # Outro usuário e um agendamento que NÃO deve aparecer
    other = CustomUser.objects.create_user(
        username="other", password="x", email="other@ex.com"
    )
    slot2 = ScheduleSlot.objects.create(
        professional=pro,
        start_time=now + timedelta(days=2),
        end_time=now + timedelta(days=2, minutes=30),
        is_available=False,
    )
    Appointment.objects.create(
        client=other,
        service=service,
        professional=pro,
        slot=slot2,
        notes="De outro user",
    )

    resp = client.get("/api/me/appointments/")
    assert resp.status_code == 200
    assert isinstance(resp.data, list)
    assert len(resp.data) == 1
    assert resp.data[0]["notes"] == "Meu agendamento"
    assert resp.data[0]["client"] == user_fixture.id
