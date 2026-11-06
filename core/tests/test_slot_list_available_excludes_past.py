from datetime import timedelta

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from core.models import Professional, ScheduleSlot


def _make_slot(professional, start_dt, status="available"):
    end_dt = start_dt + timedelta(minutes=30)
    return ScheduleSlot.objects.create(
        professional=professional,
        start_time=start_dt,
        end_time=end_dt,
        is_available=(status == "available"),
        status=status,
    )


@pytest.mark.django_db
def test_is_available_true_excludes_past_slots(user_fixture):
    client = APIClient()
    client.force_authenticate(user=user_fixture)

    prof = Professional.objects.create(user=user_fixture, name="Pro", bio="OK")
    now = timezone.now()
    past_slot = _make_slot(prof, now - timedelta(hours=1))
    future_slot = _make_slot(prof, now + timedelta(hours=1))

    resp = client.get("/api/slots/", {"is_available": "true"})
    assert resp.status_code == 200
    ids = {slot["id"] for slot in resp.data}
    assert future_slot.id in ids
    assert past_slot.id not in ids


@pytest.mark.django_db
def test_is_available_false_still_returns_past_slots(user_fixture):
    """Slots passados/indisponíveis continuam visíveis para gestão (histórico,
    bloqueios), já que o filtro de passado só se aplica ao pedir disponíveis."""
    client = APIClient()
    client.force_authenticate(user=user_fixture)

    prof = Professional.objects.create(user=user_fixture, name="Pro", bio="OK")
    now = timezone.now()
    past_blocked = _make_slot(prof, now - timedelta(hours=1), status="blocked")

    resp = client.get("/api/slots/", {"is_available": "false"})
    assert resp.status_code == 200
    ids = {slot["id"] for slot in resp.data}
    assert past_blocked.id in ids


@pytest.mark.django_db
def test_no_is_available_param_still_returns_past_slots(user_fixture):
    client = APIClient()
    client.force_authenticate(user=user_fixture)

    prof = Professional.objects.create(user=user_fixture, name="Pro", bio="OK")
    now = timezone.now()
    past_slot = _make_slot(prof, now - timedelta(hours=1))

    resp = client.get("/api/slots/")
    assert resp.status_code == 200
    ids = {slot["id"] for slot in resp.data}
    assert past_slot.id in ids
