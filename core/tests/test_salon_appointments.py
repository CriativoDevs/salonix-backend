import pytest
from datetime import timedelta
from django.utils import timezone
from rest_framework.test import APIClient

from users.models import CustomUser
from core.models import Service, Professional, ScheduleSlot, Appointment


@pytest.mark.django_db
def test_salon_owner_can_list_own_appointments(user_fixture):
    """
    O dono do salão (user_fixture) vê seus agendamentos em /api/salon/appointments/
    """
    owner = user_fixture
    client = APIClient()
    client.force_authenticate(user=owner)

    # Dados do salão do owner
    service = Service.objects.create(
        user=owner, name="Corte", duration_minutes=30, price_eur="20.00"
    )
    professional = Professional.objects.create(
        user=owner, name="Lucas", bio="Top", is_active=True
    )

    # Slot futuro
    start = timezone.now() + timedelta(days=1)
    end = start + timedelta(minutes=30)
    slot = ScheduleSlot.objects.create(
        professional=professional,
        start_time=start,
        end_time=end,
        is_available=True,
        status="available",
    )

    # Cria agendamento (cliente é o próprio owner só para simplificar o teste)
    Appointment.objects.create(
        client=owner,
        service=service,
        professional=professional,
        slot=slot,
        notes="Primeiro agendamento",
    )

    resp = client.get("/api/salon/appointments/")
    assert resp.status_code == 200
    assert isinstance(resp.data, list)
    assert len(resp.data) == 1
    assert resp.data[0]["notes"] == "Primeiro agendamento"


@pytest.mark.django_db
def test_salon_owner_can_edit_own_appointment(user_fixture):
    """
    O dono do salão consegue PATCH no seu agendamento.
    """
    owner = user_fixture
    client = APIClient()
    client.force_authenticate(user=owner)

    service = Service.objects.create(
        user=owner, name="Barba", duration_minutes=20, price_eur="15.00"
    )
    professional = Professional.objects.create(
        user=owner, name="João", bio="Experiente", is_active=True
    )
    start = timezone.now() + timedelta(days=2)
    end = start + timedelta(minutes=20)
    slot = ScheduleSlot.objects.create(
        professional=professional,
        start_time=start,
        end_time=end,
        is_available=True,
        status="available",
    )

    appt = Appointment.objects.create(
        client=owner,
        service=service,
        professional=professional,
        slot=slot,
        notes="Para editar",
    )

    resp = client.patch(
        f"/api/salon/appointments/{appt.id}/",
        data={"notes": "Notas atualizadas via PATCH"},
        format="json",
    )
    assert resp.status_code == 200
    assert resp.data["notes"] == "Notas atualizadas via PATCH"


@pytest.mark.django_db
def test_other_user_cannot_view_or_edit_salon_appointments(user_fixture):
    """
    Outro usuário não vê agendamentos do salão alheio (lista vazia)
    e não consegue editar (403 por falta de permissão).
    """
    owner = user_fixture
    other = CustomUser.objects.create_user(
        username="other", email="other@example.com", password="pass1234"
    )

    # Cria dados do owner
    service = Service.objects.create(
        user=owner, name="Coloração", duration_minutes=45, price_eur="35.00"
    )
    professional = Professional.objects.create(
        user=owner, name="Maria", bio="Colorista", is_active=True
    )
    start = timezone.now() + timedelta(days=3)
    end = start + timedelta(minutes=45)
    slot = ScheduleSlot.objects.create(
        professional=professional,
        start_time=start,
        end_time=end,
        is_available=True,
        status="available",
    )
    appt = Appointment.objects.create(
        client=owner,
        service=service,
        professional=professional,
        slot=slot,
        notes="Do salão do owner",
    )

    client = APIClient()
    client.force_authenticate(user=other)

    # Lista deve vir vazia para "other"
    list_resp = client.get("/api/salon/appointments/")
    assert list_resp.status_code == 200
    assert isinstance(list_resp.data, list)
    assert len(list_resp.data) == 0

    # Tentar editar deve dar 403 (objeto existe, mas sem permissão)
    patch_resp = client.patch(
        f"/api/salon/appointments/{appt.id}/",
        data={"notes": "tentativa não autorizada"},
        format="json",
    )
    assert patch_resp.status_code == 403
