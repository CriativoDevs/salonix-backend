import pytest
from rest_framework.test import APIClient
from core.models import Appointment, Service, Professional, ScheduleSlot
from django.utils import timezone
from datetime import timedelta
from unittest.mock import patch


@pytest.mark.django_db
@patch("core.views.send_appointment_cancellation_email")
def test_cancel_appointment(mock_send_email, user_fixture):
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

    # Verifica se o e-mail foi enviado
    assert mock_send_email.called is True
    args, kwargs = mock_send_email.call_args
    assert kwargs["client_email"] == user_fixture.email
    assert kwargs["salon_email"] == professional.user.email
    assert kwargs["service_name"] == service.name
