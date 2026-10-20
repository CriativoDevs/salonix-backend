import pytest
from datetime import timedelta
from django.utils import timezone
from rest_framework.test import APIClient

from core.models import Professional, ScheduleSlot


def _make_slot(professional, start_dt, status="available"):
    end_dt = start_dt + timedelta(minutes=30)
    slot = ScheduleSlot.objects.create(
        professional=professional,
        start_time=start_dt,
        end_time=end_dt,
        is_available=(status == "available"),
        status=status,
    )
    return slot


@pytest.mark.django_db
def test_default_pagination_headers(user_fixture):
    client = APIClient()
    client.force_authenticate(user=user_fixture)

    prof = Professional.objects.create(user=user_fixture, name="Pro", bio="OK")
    now = timezone.now()
    for i in range(25):
        _make_slot(prof, now + timedelta(hours=i))

    resp = client.get("/api/slots/")
    assert resp.status_code == 200
    assert isinstance(resp.data, list)
    assert len(resp.data) == 20

    assert resp["X-Total-Count"] == "25"
    assert resp["X-Limit"] == "20"
    assert resp["X-Offset"] == "0"
    assert 'rel="next"' in resp.get("Link", "")


@pytest.mark.django_db
def test_limit_offset_respected(user_fixture):
    client = APIClient()
    client.force_authenticate(user=user_fixture)

    prof = Professional.objects.create(user=user_fixture, name="Pro", bio="OK")
    now = timezone.now()
    for i in range(15):
        _make_slot(prof, now + timedelta(hours=i))

    resp = client.get("/api/slots/", {"limit": 5, "offset": 5})
    assert resp.status_code == 200
    assert len(resp.data) == 5
    assert resp["X-Total-Count"] == "15"
    assert resp["X-Limit"] == "5"
    assert resp["X-Offset"] == "5"


@pytest.mark.django_db
def test_mixed_statuses_counted_in_total(user_fixture):
    # Garante que o total agregue available/blocked/booked -- é exatamente
    # o caso que estourou a paginação na tela de gestão (antes do fix).
    client = APIClient()
    client.force_authenticate(user=user_fixture)

    prof = Professional.objects.create(user=user_fixture, name="Pro", bio="OK")
    now = timezone.now()
    for i in range(3):
        _make_slot(prof, now + timedelta(hours=i), status="available")
    for i in range(3, 6):
        _make_slot(prof, now + timedelta(hours=i), status="blocked")
    for i in range(6, 9):
        _make_slot(prof, now + timedelta(hours=i), status="booked")

    resp = client.get("/api/slots/")
    assert resp.status_code == 200
    assert resp["X-Total-Count"] == "9"
    assert len(resp.data) == 9
