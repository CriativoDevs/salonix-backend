import pytest
from unittest.mock import patch
from datetime import timedelta

from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework import status

from core.models import Appointment, Service, Professional, ScheduleSlot
from users.models import CustomUser


@pytest.fixture
def salon_owner(db):
    return CustomUser.objects.create_user(
        username="salon", password="pass", email="salon@example.com"
    )


@pytest.fixture
def client_user(db):
    return CustomUser.objects.create_user(
        username="client", password="pass", email="client@example.com", first_name="Ana"
    )


@pytest.fixture
def base_setup(db, salon_owner, client_user):
    # salão "dono" de service e professional
    service = Service.objects.create(
        user=salon_owner, name="Corte", duration_minutes=30, price_eur="20.00"
    )
    prof = Professional.objects.create(
        user=salon_owner, name="João", bio="Top", is_active=True
    )
    now = timezone.now()
    slot_a = ScheduleSlot.objects.create(
        professional=prof,
        start_time=now + timedelta(days=1, hours=1),
        end_time=now + timedelta(days=1, hours=1, minutes=30),
        is_available=True,
        status="available",
    )
    slot_b = ScheduleSlot.objects.create(
        professional=prof,
        start_time=now + timedelta(days=1, hours=2),
        end_time=now + timedelta(days=1, hours=2, minutes=30),
        is_available=True,
        status="available",
    )
    # ocupa slot_a e cria appointment
    slot_a.mark_booked()
    appt = Appointment.objects.create(
        client=client_user,
        service=service,
        professional=prof,
        slot=slot_a,
        notes="n/a",
    )
    return {
        "service": service,
        "prof": prof,
        "slot_a": slot_a,
        "slot_b": slot_b,
        "appt": appt,
        "salon_owner": salon_owner,
        "client_user": client_user,
    }


def auth_client(user):
    c = APIClient()
    c.force_authenticate(user=user)
    return c


@pytest.mark.django_db
def test_update_notes(base_setup):
    c = auth_client(base_setup["salon_owner"])
    appt = base_setup["appt"]

    resp = c.patch(
        f"/api/salon/appointments/{appt.id}/", {"notes": "Trazer foto"}, format="json"
    )
    assert resp.status_code == status.HTTP_200_OK
    appt.refresh_from_db()
    assert appt.notes == "Trazer foto"


@pytest.mark.django_db
def test_reschedule_to_free_slot(base_setup):
    c = auth_client(base_setup["salon_owner"])
    appt = base_setup["appt"]
    old_slot = base_setup["slot_a"]
    new_slot = base_setup["slot_b"]

    resp = c.patch(
        f"/api/salon/appointments/{appt.id}/", {"slot": new_slot.id}, format="json"
    )
    assert resp.status_code == status.HTTP_200_OK

    appt.refresh_from_db()
    old_slot.refresh_from_db()
    new_slot.refresh_from_db()

    assert appt.slot_id == new_slot.id
    assert old_slot.is_available is True and old_slot.status == "available"
    assert new_slot.is_available is False and new_slot.status == "booked"


@pytest.mark.django_db
def test_reschedule_to_occupied_slot_returns_400(base_setup):
    c = auth_client(base_setup["salon_owner"])
    appt = base_setup["appt"]

    # cria outro slot e marca como ocupado
    now = timezone.now()
    busy_slot = ScheduleSlot.objects.create(
        professional=base_setup["prof"],
        start_time=now + timedelta(days=1, hours=3),
        end_time=now + timedelta(days=1, hours=3, minutes=30),
        is_available=True,
        status="available",
    )
    busy_slot.mark_booked()

    resp = c.patch(
        f"/api/salon/appointments/{appt.id}/", {"slot": busy_slot.id}, format="json"
    )
    assert resp.status_code == status.HTTP_400_BAD_REQUEST
    # Com novo sistema de erros, a estrutura mudou
    assert "error" in resp.data
    assert "slot" in resp.data["error"]["details"]


@pytest.mark.django_db
@patch("core.views.send_appointment_cancellation_email")
def test_cancel_sends_email_and_frees_slot(mock_email, base_setup):
    c = auth_client(base_setup["salon_owner"])
    appt = base_setup["appt"]
    slot = base_setup["slot_a"]

    resp = c.patch(
        f"/api/salon/appointments/{appt.id}/", {"status": "cancelled"}, format="json"
    )
    assert resp.status_code == status.HTTP_200_OK

    appt.refresh_from_db()
    slot.refresh_from_db()

    assert appt.status == "cancelled"
    assert appt.cancelled_by == base_setup["salon_owner"]
    assert slot.is_available is True and slot.status == "available"

    assert mock_email.called is True
    _, kwargs = mock_email.call_args
    assert kwargs["client_email"] == base_setup["client_user"].email
    assert kwargs["salon_email"] == base_setup["salon_owner"].email
    assert kwargs["service_name"] == base_setup["service"].name


@pytest.mark.django_db
def test_edit_from_other_salon_forbidden(base_setup, django_user_model):
    other_owner = django_user_model.objects.create_user(
        username="other", password="pass", email="other@example.com"
    )
    c = auth_client(other_owner)
    appt = base_setup["appt"]

    resp = c.patch(
        f"/api/salon/appointments/{appt.id}/", {"notes": "hack"}, format="json"
    )
    assert resp.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.django_db
def test_cancel_already_cancelled_returns_400(base_setup):
    c = auth_client(base_setup["salon_owner"])
    appt = base_setup["appt"]

    # primeiro cancelamento
    r1 = c.patch(
        f"/api/salon/appointments/{appt.id}/", {"status": "cancelled"}, format="json"
    )
    assert r1.status_code == status.HTTP_200_OK

    # segundo cancelamento -> 400
    r2 = c.patch(
        f"/api/salon/appointments/{appt.id}/", {"status": "cancelled"}, format="json"
    )
    assert r2.status_code == status.HTTP_400_BAD_REQUEST
