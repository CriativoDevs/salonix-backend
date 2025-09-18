from datetime import timedelta

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from core.models import (
    Appointment,
    AppointmentSeries,
    Professional,
    ScheduleSlot,
    Service,
)


@pytest.mark.django_db
def test_series_cancel_all_future_appointments(user_fixture):
    client = APIClient()
    client.force_authenticate(user=user_fixture)

    service = Service.objects.create(
        user=user_fixture, name="Corte", price_eur=30, duration_minutes=45
    )
    professional = Professional.objects.create(user=user_fixture, name="João")
    series = AppointmentSeries.objects.create(
        tenant=user_fixture.tenant,
        client=user_fixture,
        service=service,
        professional=professional,
        notes="Série inicial",
    )

    now = timezone.now()

    # Passado permanece intacto
    past_slot = ScheduleSlot.objects.create(
        professional=professional,
        start_time=now - timedelta(days=10),
        end_time=now - timedelta(days=10) + timedelta(minutes=45),
    )
    past_slot.mark_booked()
    past_appointment = Appointment.objects.create(
        client=user_fixture,
        service=service,
        professional=professional,
        slot=past_slot,
        status="completed",
        series=series,
    )

    # Futuro deve ser cancelado
    future_appointments = []
    for days_ahead in (3, 6):
        slot = ScheduleSlot.objects.create(
            professional=professional,
            start_time=now + timedelta(days=days_ahead),
            end_time=now + timedelta(days=days_ahead, minutes=45),
        )
        slot.mark_booked()
        appointment = Appointment.objects.create(
            client=user_fixture,
            service=service,
            professional=professional,
            slot=slot,
            status="scheduled",
            series=series,
        )
        future_appointments.append((appointment, slot))

    response = client.patch(
        f"/api/appointments/series/{series.id}/",
        {"action": "cancel_all"},
        format="json",
    )

    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["series_id"] == series.id
    assert data["affected_count"] == 2
    assert set(data["appointment_ids"]) == {appt.id for appt, _ in future_appointments}

    for appointment, slot in future_appointments:
        appointment.refresh_from_db()
        slot.refresh_from_db()
        assert appointment.status == "cancelled"
        assert appointment.cancelled_by == user_fixture
        assert slot.is_available is True
        assert slot.status == "available"

    past_appointment.refresh_from_db()
    assert past_appointment.status == "completed"


@pytest.mark.django_db
def test_series_edit_upcoming_updates_notes_and_slots(user_fixture):
    client = APIClient()
    client.force_authenticate(user=user_fixture)

    service = Service.objects.create(
        user=user_fixture, name="Coloração", price_eur=50, duration_minutes=60
    )
    professional = Professional.objects.create(user=user_fixture, name="Maria")
    series = AppointmentSeries.objects.create(
        tenant=user_fixture.tenant,
        client=user_fixture,
        service=service,
        professional=professional,
        notes="Notas originais",
    )

    now = timezone.now()

    original_slots = []
    upcoming_appointments = []
    for days_ahead in (2, 4):
        slot = ScheduleSlot.objects.create(
            professional=professional,
            start_time=now + timedelta(days=days_ahead),
            end_time=now + timedelta(days=days_ahead, minutes=60),
        )
        slot.mark_booked()
        appointment = Appointment.objects.create(
            client=user_fixture,
            service=service,
            professional=professional,
            slot=slot,
            status="scheduled",
            series=series,
        )
        original_slots.append(slot)
        upcoming_appointments.append(appointment)

    # slots disponíveis para remarcação
    new_slots = []
    for days_ahead in (5, 7):
        slot = ScheduleSlot.objects.create(
            professional=professional,
            start_time=now + timedelta(days=days_ahead),
            end_time=now + timedelta(days=days_ahead, minutes=60),
        )
        new_slots.append(slot)

    payload = {
        "action": "edit_upcoming",
        "notes": "Notas atualizadas",
        "slot_ids": [slot.id for slot in new_slots],
    }

    response = client.patch(
        f"/api/appointments/series/{series.id}/",
        payload,
        format="json",
    )

    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["affected_count"] == 2
    assert set(data["appointment_ids"]) == {appt.id for appt in upcoming_appointments}

    for appointment, new_slot in zip(upcoming_appointments, new_slots):
        appointment.refresh_from_db()
        new_slot.refresh_from_db()
        assert appointment.slot_id == new_slot.id
        assert appointment.notes == "Notas atualizadas"
        assert new_slot.is_available is False
        assert new_slot.status == "booked"

    for slot in original_slots:
        slot.refresh_from_db()
        assert slot.is_available is True
        assert slot.status == "available"

    series.refresh_from_db()
    assert series.notes == "Notas atualizadas"


@pytest.mark.django_db
def test_series_edit_upcoming_slot_count_mismatch(user_fixture):
    client = APIClient()
    client.force_authenticate(user=user_fixture)

    service = Service.objects.create(
        user=user_fixture, name="Tratamento", price_eur=80, duration_minutes=90
    )
    professional = Professional.objects.create(user=user_fixture, name="Ana")
    series = AppointmentSeries.objects.create(
        tenant=user_fixture.tenant,
        client=user_fixture,
        service=service,
        professional=professional,
    )

    now = timezone.now()
    for days_ahead in (1, 2):
        slot = ScheduleSlot.objects.create(
            professional=professional,
            start_time=now + timedelta(days=days_ahead),
            end_time=now + timedelta(days=days_ahead, minutes=90),
        )
        slot.mark_booked()
        Appointment.objects.create(
            client=user_fixture,
            service=service,
            professional=professional,
            slot=slot,
            status="scheduled",
            series=series,
        )

    # Apenas um slot novo informado para dois agendamentos → erro
    available_slot = ScheduleSlot.objects.create(
        professional=professional,
        start_time=now + timedelta(days=5),
        end_time=now + timedelta(days=5, minutes=90),
    )

    response = client.patch(
        f"/api/appointments/series/{series.id}/",
        {"action": "edit_upcoming", "slot_ids": [available_slot.id]},
        format="json",
    )

    assert response.status_code == 400
    assert "slot_ids" in response.json()


@pytest.mark.django_db
def test_series_occurrence_cancel_success(user_fixture):
    client = APIClient()
    client.force_authenticate(user=user_fixture)

    service = Service.objects.create(
        user=user_fixture, name="Massagem", price_eur=60, duration_minutes=60
    )
    professional = Professional.objects.create(user=user_fixture, name="Clara")
    series = AppointmentSeries.objects.create(
        tenant=user_fixture.tenant,
        client=user_fixture,
        service=service,
        professional=professional,
    )

    now = timezone.now()
    slot = ScheduleSlot.objects.create(
        professional=professional,
        start_time=now + timedelta(days=1),
        end_time=now + timedelta(days=1, minutes=60),
    )
    slot.mark_booked()
    appointment = Appointment.objects.create(
        client=user_fixture,
        service=service,
        professional=professional,
        slot=slot,
        series=series,
        status="scheduled",
    )

    response = client.post(
        f"/api/appointments/series/{series.id}/occurrence/{appointment.id}/cancel/",
        format="json",
    )

    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["appointment_id"] == appointment.id

    appointment.refresh_from_db()
    slot.refresh_from_db()
    assert appointment.status == "cancelled"
    assert appointment.cancelled_by == user_fixture
    assert slot.is_available is True
    assert slot.status == "available"


@pytest.mark.django_db
def test_series_occurrence_cancel_past_fails(user_fixture):
    client = APIClient()
    client.force_authenticate(user=user_fixture)

    service = Service.objects.create(
        user=user_fixture, name="Limpeza", price_eur=40, duration_minutes=45
    )
    professional = Professional.objects.create(user=user_fixture, name="Bruno")
    series = AppointmentSeries.objects.create(
        tenant=user_fixture.tenant,
        client=user_fixture,
        service=service,
        professional=professional,
    )

    now = timezone.now()
    slot = ScheduleSlot.objects.create(
        professional=professional,
        start_time=now - timedelta(days=1),
        end_time=now - timedelta(days=1) + timedelta(minutes=45),
    )
    slot.mark_booked()
    appointment = Appointment.objects.create(
        client=user_fixture,
        service=service,
        professional=professional,
        slot=slot,
        series=series,
        status="scheduled",
    )

    response = client.post(
        f"/api/appointments/series/{series.id}/occurrence/{appointment.id}/cancel/",
        format="json",
    )

    assert response.status_code == 400
    assert "detail" in response.json()


@pytest.mark.django_db
def test_series_occurrence_cancel_forbidden(user_fixture, django_user_model):
    client = APIClient()
    client.force_authenticate(user=user_fixture)

    other_user = django_user_model.objects.create_user(
        username="tenant-two",
        password="pass",
        email="tenant-two@example.com",
    )

    service = Service.objects.create(
        user=other_user, name="SPA", price_eur=90, duration_minutes=90
    )
    professional = Professional.objects.create(user=other_user, name="Helena")
    series = AppointmentSeries.objects.create(
        tenant=other_user.tenant,
        client=other_user,
        service=service,
        professional=professional,
    )

    now = timezone.now()
    slot = ScheduleSlot.objects.create(
        professional=professional,
        start_time=now + timedelta(days=2),
        end_time=now + timedelta(days=2, minutes=90),
    )
    slot.mark_booked()
    appointment = Appointment.objects.create(
        client=other_user,
        service=service,
        professional=professional,
        slot=slot,
        series=series,
        status="scheduled",
    )

    response = client.post(
        f"/api/appointments/series/{series.id}/occurrence/{appointment.id}/cancel/"
    )

    assert response.status_code == 403
