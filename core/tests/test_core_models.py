# core/tests/test_core_models.py
import pytest
from core.models import Service, Professional, ScheduleSlot, Appointment
from django.utils import timezone
from datetime import timedelta


@pytest.mark.django_db
def test_create_service(user_fixture):
    service = Service.objects.create(
        user=user_fixture,
        name="Corte de Cabelo",
        price_eur=15.00,
        duration_minutes=30,
    )
    assert service.name == "Corte de Cabelo"


@pytest.mark.django_db
def test_create_professional(user_fixture):
    professional = Professional.objects.create(
        user=user_fixture,
        name="João Silva",
        bio="Especialista em cortes masculinos.",
    )
    assert professional.name == "João Silva"


@pytest.mark.django_db
def test_create_schedule_slot(user_fixture):
    professional = Professional.objects.create(user=user_fixture, name="Maria")

    start = timezone.now()
    end = start + timedelta(minutes=30)
    slot = ScheduleSlot.objects.create(
        professional=professional, start_time=start, end_time=end
    )
    assert slot.is_available is True


@pytest.mark.django_db
def test_create_appointment(user_fixture):
    service = Service.objects.create(
        user=user_fixture, name="Manicure", price_eur=20.0, duration_minutes=45
    )
    professional = Professional.objects.create(user=user_fixture, name="Ana")
    start = timezone.now()
    end = start + timedelta(minutes=45)
    slot = ScheduleSlot.objects.create(
        professional=professional, start_time=start, end_time=end
    )
    appointment = Appointment.objects.create(
        client=user_fixture,
        service=service,
        professional=professional,
        slot=slot,
        notes="Cliente prefere esmalte vermelho.",
    )
    assert appointment.client.username == "testuser"
