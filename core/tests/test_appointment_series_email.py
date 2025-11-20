import datetime
import pytz
from unittest.mock import patch

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from core.models import Service, Professional, ScheduleSlot


@pytest.mark.django_db
@patch("core.email_utils.send_bulk_appointment_confirmation_email")
def test_series_create_sends_consolidated_email(mock_send, tenant_fixture, user_fixture):
    client = APIClient()
    client.force_authenticate(user=user_fixture)

    # Dados base
    service = Service.objects.create(
        tenant=tenant_fixture,
        user=user_fixture,
        name="Sobrancelha",
        duration_minutes=30,
        price_eur="20.00",
    )

    professional = Professional.objects.create(
        tenant=tenant_fixture, user=user_fixture, name="Luiz", bio="Top", is_active=True
    )

    tz = pytz.timezone("Europe/Lisbon")
    now = timezone.now().astimezone(tz)
    start1 = now + datetime.timedelta(days=1)
    start2 = now + datetime.timedelta(days=3, hours=1)
    start3 = now + datetime.timedelta(days=7, hours=2)

    slot1 = ScheduleSlot.objects.create(
        tenant=tenant_fixture,
        professional=professional,
        start_time=start1,
        end_time=start1 + datetime.timedelta(minutes=30),
        is_available=True,
    )
    slot2 = ScheduleSlot.objects.create(
        tenant=tenant_fixture,
        professional=professional,
        start_time=start2,
        end_time=start2 + datetime.timedelta(minutes=30),
        is_available=True,
    )
    slot3 = ScheduleSlot.objects.create(
        tenant=tenant_fixture,
        professional=professional,
        start_time=start3,
        end_time=start3 + datetime.timedelta(minutes=30),
        is_available=True,
    )

    payload = {
        "service_id": service.id,
        "professional_id": professional.id,
        "client_name": "Alana Nogueira",
        "client_email": "alana@example.com",
        "appointments": [
            {"slot_id": slot1.id},
            {"slot_id": slot2.id},
            {"slot_id": slot3.id},
        ],
        "notes": "Série de 3 sessões",
    }

    resp = client.post("/api/appointments/series/", data=payload, format="json")
    assert resp.status_code == 201
    data = resp.json()
    assert data["appointments_created"] == 3
    assert len(data["appointment_ids"]) == 3

    # Verifica envio consolidado
    mock_send.assert_called_once()
    args, kwargs = mock_send.call_args
    assert kwargs["to_email"] == "alana@example.com"
    assert kwargs["client_name"] == "Alana Nogueira"
    assert kwargs["salon_name"]
    assert isinstance(kwargs["items"], list) and len(kwargs["items"]) == 3
    assert all("appointment_id" in it for it in kwargs["items"])  # IDs presentes


@pytest.mark.django_db
@patch("core.email_utils.send_bulk_appointment_confirmation_email", side_effect=Exception("SMTP down"))
def test_series_create_email_failure_does_not_break_flow(mock_send, tenant_fixture, user_fixture):
    client = APIClient()
    client.force_authenticate(user=user_fixture)

    service = Service.objects.create(
        tenant=tenant_fixture,
        user=user_fixture,
        name="Hidratação",
        duration_minutes=60,
        price_eur="35.00",
    )
    professional = Professional.objects.create(
        tenant=tenant_fixture, user=user_fixture, name="Ian Pinto", bio="Bio", is_active=True
    )

    tz = pytz.timezone("Europe/Lisbon")
    start = timezone.now().astimezone(tz) + datetime.timedelta(days=2)
    slot = ScheduleSlot.objects.create(
        tenant=tenant_fixture,
        professional=professional,
        start_time=start,
        end_time=start + datetime.timedelta(minutes=60),
        is_available=True,
    )

    payload = {
        "service_id": service.id,
        "professional_id": professional.id,
        "client_name": "Cliente",
        "client_email": "cliente@example.com",
        "appointments": [{"slot_id": slot.id}],
        "notes": "Teste falha email",
    }

    resp = client.post("/api/appointments/series/", data=payload, format="json")
    # Apesar da falha ao enviar e-mail, a criação deve acontecer normalmente
    assert resp.status_code == 201
    data = resp.json()
    assert data["appointments_created"] == 1
    assert len(data["appointment_ids"]) == 1
    # Função de e-mail foi chamada e falhou
    mock_send.assert_called_once()