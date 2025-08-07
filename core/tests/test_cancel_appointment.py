import pytest
from rest_framework.test import APIClient
from core.models import Appointment, Service, Professional, ScheduleSlot
from django.utils import timezone
from datetime import timedelta


@pytest.mark.django_db
def test_cancel_appointment(user_fixture):
    client = APIClient()
    client.force_authenticate(user=user_fixture)

    # Cria instâncias reais
    service = Service.objects.create(
        user=user_fixture, name="Corte de Cabelo", price_eur=20, duration_minutes=30
    )

    professional = Professional.objects.create(
        user=user_fixture, name="João", bio="Profissional experiente"
    )

    now = timezone.now()
    slot = ScheduleSlot.objects.create(
        professional=professional,
        start_time=now + timedelta(days=1),
        end_time=now + timedelta(days=1, minutes=30),
        is_available=False,  # será reativado após cancelamento
    )

    appointment = Appointment.objects.create(
        client=user_fixture,
        service=service,
        professional=professional,
        slot=slot,
        notes="Teste de cancelamento",
    )

    response = client.patch(f"/api/appointments/{appointment.id}/cancel/")
    assert response.status_code == 200

    appointment.refresh_from_db()
    assert appointment.status == "cancelled"
    assert appointment.cancelled_by == user_fixture
    assert appointment.slot.is_available is True
