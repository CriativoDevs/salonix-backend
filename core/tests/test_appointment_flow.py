import datetime
import pytz
import pytest
from rest_framework.test import APIClient
from core.models import Service, Professional, ScheduleSlot, Appointment
from typing import cast
from users.models import CustomUser, TenantStaffMember


@pytest.mark.django_db
def test_create_service(user_fixture):
    client = APIClient()
    client.force_authenticate(user=user_fixture)

    payload = {"name": "Corte Masculino", "duration_minutes": 30, "price_eur": "15.00"}

    response = client.post("/api/services/", data=payload, format="json")

    print("\nResponse data:", response.data)

    assert response.status_code == 201
    assert Service.objects.count() == 1
    service_created = Service.objects.first()
    assert service_created is not None
    service_created = cast(Service, service_created)
    assert service_created.name == "Corte Masculino"


@pytest.mark.django_db
def test_create_professional(user_fixture):
    client = APIClient()
    client.force_authenticate(user=user_fixture)

    collaborator_user = CustomUser.objects.create_user(
        username="collab_professional",
        email="collab_professional@example.com",
        password="testpass123",
        tenant=user_fixture.tenant,
    )
    collaborator_staff = TenantStaffMember.objects.create(
        tenant=user_fixture.tenant,
        user=collaborator_user,
        role=TenantStaffMember.Role.COLLABORATOR,
        status=TenantStaffMember.Status.ACTIVE,
    )

    payload = {
        "name": "Lucas Silva",
        "bio": "Especialista em cortes modernos",
        "is_active": True,
        "staff_member": collaborator_staff.id,
    }

    response = client.post("/api/professionals/", data=payload, format="json")
    print("\nResponse data (professional):", response.data)

    assert response.status_code == 201
    assert Professional.objects.count() == 1
    professional_created = Professional.objects.first()
    assert professional_created is not None
    professional_created = cast(Professional, professional_created)
    assert professional_created.name == "Lucas Silva"
    assert professional_created.staff_member == collaborator_staff
    assert professional_created.user == collaborator_user


@pytest.mark.django_db
def test_create_slot(user_fixture):
    client = APIClient()
    client.force_authenticate(user=user_fixture)

    collaborator_user = CustomUser.objects.create_user(
        username="collab_slot",
        email="collab_slot@example.com",
        password="testpass123",
        tenant=user_fixture.tenant,
    )
    collaborator_staff = TenantStaffMember.objects.create(
        tenant=user_fixture.tenant,
        user=collaborator_user,
        role=TenantStaffMember.Role.COLLABORATOR,
        status=TenantStaffMember.Status.ACTIVE,
    )

    # Cria um profissional
    professional = Professional.objects.create(
        user=collaborator_user,
        staff_member=collaborator_staff,
        name="Lucas Silva",
        bio="Barbeiro top",
        is_active=True,
        tenant=user_fixture.tenant,
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
    assert slot is not None
    slot = cast(ScheduleSlot, slot)
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
    collaborator_user = CustomUser.objects.create_user(
        username="collab_appointment",
        email="collab_appointment@example.com",
        password="testpass123",
        tenant=user_fixture.tenant,
    )
    collaborator_staff = TenantStaffMember.objects.create(
        tenant=user_fixture.tenant,
        user=collaborator_user,
        role=TenantStaffMember.Role.COLLABORATOR,
        status=TenantStaffMember.Status.ACTIVE,
    )
    professional = Professional.objects.create(
        user=collaborator_user,
        staff_member=collaborator_staff,
        tenant=user_fixture.tenant,
        name="Lucas",
        bio="Top",
        is_active=True,
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
    assert appointment is not None
    appointment = cast(Appointment, appointment)
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
    collaborator_user = CustomUser.objects.create_user(
        username="collab_unavailable",
        email="collab_unavailable@example.com",
        password="testpass123",
        tenant=user_fixture.tenant,
    )
    collaborator_staff = TenantStaffMember.objects.create(
        tenant=user_fixture.tenant,
        user=collaborator_user,
        role=TenantStaffMember.Role.COLLABORATOR,
        status=TenantStaffMember.Status.ACTIVE,
    )
    professional = Professional.objects.create(
        user=collaborator_user,
        staff_member=collaborator_staff,
        tenant=user_fixture.tenant,
        name="Lucas",
        bio="Top",
        is_active=True,
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
        user=user_fixture,
        staff_member=user_fixture.staff_member,
        tenant=user_fixture.tenant,
        name="João",
        bio="Top",
        is_active=True,
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
