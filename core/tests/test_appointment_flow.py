import datetime
import pytz
import pytest
from rest_framework.test import APIClient
from core.models import Service, Professional, ScheduleSlot, Appointment


@pytest.mark.django_db
def test_create_service(user_fixture):
    client = APIClient()
    client.force_authenticate(user=user_fixture)

    payload = {"name": "Corte Masculino", "duration_minutes": 30, "price_eur": "15.00"}

    response = client.post("/api/services/", data=payload, format="json")

    print("\nResponse data:", response.data)

    assert response.status_code == 201
    assert Service.objects.count() == 1
    assert Service.objects.first().name == "Corte Masculino"


@pytest.mark.django_db
def test_create_professional(user_fixture):
    client = APIClient()
    client.force_authenticate(user=user_fixture)

    payload = {
        "name": "Lucas Silva",
        "bio": "Especialista em cortes modernos",
        "is_active": True,
    }

    response = client.post("/api/professionals/", data=payload, format="json")
    print("\nResponse data (professional):", response.data)

    assert response.status_code == 201
    assert Professional.objects.count() == 1
    assert Professional.objects.first().name == "Lucas Silva"


@pytest.mark.django_db
def test_create_slot(user_fixture):
    client = APIClient()
    client.force_authenticate(user=user_fixture)

    # Cria um profissional
    professional = Professional.objects.create(
        user=user_fixture, name="Lucas Silva", bio="Barbeiro top", is_active=True
    )

    # Define horários válidos
    tz = pytz.timezone("Europe/Lisbon")
    now = datetime.datetime.now(tz=tz)
    start_time = now + datetime.timedelta(days=1, hours=2)
    end_time = start_time + datetime.timedelta(minutes=30)

    payload = {
        "professional": professional.id,
        "start_time": start_time.isoformat(),
        "end_time": end_time.isoformat(),
        "is_available": True,
    }

    response = client.post("/api/slots/", data=payload, format="json")
    print("\nResponse data (slot):", response.data)

    assert response.status_code == 201
    assert ScheduleSlot.objects.count() == 1
    slot = ScheduleSlot.objects.first()
    assert slot.professional == professional
    assert slot.is_available is True


@pytest.mark.django_db
def test_create_appointment(user_fixture):
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
    start_time = now + datetime.timedelta(days=1, hours=1)
    end_time = start_time + datetime.timedelta(minutes=30)

    slot = ScheduleSlot.objects.create(
        professional=professional,
        start_time=start_time,
        end_time=end_time,
        is_available=True,
    )

    # Payload para criar o agendamento
    payload = {
        "service": service.id,
        "professional": professional.id,
        "slot": slot.id,
        "notes": "Por favor, fazer a barba também",
    }

    response = client.post("/api/appointments/", data=payload, format="json")
    print("\nResponse data (appointment):", response.data)

    assert response.status_code == 201
    assert Appointment.objects.count() == 1
    appointment = Appointment.objects.first()
    assert appointment.client == user_fixture
    assert appointment.service == service
    assert appointment.professional == professional
    assert appointment.slot == slot
    assert appointment.notes == "Por favor, fazer a barba também"
    assert appointment.slot.is_available is False  # slot foi marcado como indisponível


@pytest.mark.django_db
def test_appointment_with_unavailable_slot(user_fixture):
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

    # Cria slot indisponível
    tz = pytz.timezone("Europe/Lisbon")
    now = datetime.datetime.now(tz=tz)
    start_time = now + datetime.timedelta(days=1, hours=2)
    end_time = start_time + datetime.timedelta(minutes=30)

    slot = ScheduleSlot.objects.create(
        professional=professional,
        start_time=start_time,
        end_time=end_time,
        is_available=False,
    )

    payload = {
        "service": service.id,
        "professional": professional.id,
        "slot": slot.id,
        "notes": "Agendamento com slot ocupado",
    }

    response = client.post("/api/appointments/", data=payload, format="json")
    print("\nResponse data (slot indisponível):", response.data)

    assert response.status_code == 400
    assert "já foi agendado" in response.content.decode("utf-8")


@pytest.mark.django_db
def test_appointment_unauthenticated(user_fixture):
    # Cria dados como antes
    service = Service.objects.create(
        user=user_fixture, name="Barba", duration_minutes=30, price_eur="15.00"
    )
    professional = Professional.objects.create(
        user=user_fixture, name="João", bio="Top", is_active=True
    )

    tz = pytz.timezone("Europe/Lisbon")
    start_time = datetime.datetime.now(tz) + datetime.timedelta(days=1)
    end_time = start_time + datetime.timedelta(minutes=30)

    slot = ScheduleSlot.objects.create(
        professional=professional,
        start_time=start_time,
        end_time=end_time,
        is_available=True,
    )

    payload = {
        "service": service.id,
        "professional": professional.id,
        "slot": slot.id,
        "notes": "Sem login",
    }

    client = APIClient()  # não autenticado
    response = client.post("/api/appointments/", data=payload, format="json")
    assert response.status_code == 401


@pytest.mark.django_db
def test_appointment_with_invalid_ids(user_fixture):
    client = APIClient()
    client.force_authenticate(user=user_fixture)

    payload = {
        "service": 9999,
        "professional": 8888,
        "slot": 7777,
        "notes": "IDs inválidos",
    }

    response = client.post("/api/appointments/", data=payload, format="json")
    print("\nResponse data (dados inválidos):", response.data)
    assert response.status_code == 400
