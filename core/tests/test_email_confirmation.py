import datetime
import pytz
import pytest
from unittest.mock import patch
from rest_framework.test import APIClient

from core.models import Service, Professional, ScheduleSlot, Appointment


@pytest.mark.django_db
@patch("core.views.send_appointment_confirmation_email")
def test_send_email_on_appointment_creation(mock_send_email, user_fixture):
    client = APIClient()
    client.force_authenticate(user=user_fixture)

    # Cria serviço
    service = Service.objects.create(
        user=user_fixture, name="Corte", duration_minutes=30, price_eur="20.00"
    )

    # Cria profissional
    professional = Professional.objects.create(
        user=user_fixture, name="Lucas", bio="Top", is_active=True
    )

    # Cria slot
    tz = pytz.timezone("Europe/Lisbon")
    now = datetime.datetime.now(tz=tz)
    start_time = now + datetime.timedelta(days=1)
    end_time = start_time + datetime.timedelta(minutes=30)

    slot = ScheduleSlot.objects.create(
        professional=professional,
        start_time=start_time,
        end_time=end_time,
        is_available=True,
    )

    # Payload do agendamento
    payload = {
        "service": service.id,
        "professional": professional.id,
        "slot": slot.id,
        "notes": "Com barba",
    }

    response = client.post("/api/appointments/", data=payload, format="json")
    assert response.status_code == 201

    # Verifica se e-mail foi enviado
    mock_send_email.assert_called_once()

    args, kwargs = mock_send_email.call_args
    assert kwargs["to_email"] == user_fixture.email
    assert "Corte" in kwargs["service_name"]
    assert kwargs["date_time"] == start_time
