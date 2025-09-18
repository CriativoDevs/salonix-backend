import pytest
from prometheus_client import CollectorRegistry, Counter
from rest_framework.test import APIClient

from core import views as series_views
from core.models import Appointment, AppointmentSeries, Professional, ScheduleSlot, Service
from django.utils import timezone
from datetime import timedelta


@pytest.fixture
def api_client(user_fixture):
    client = APIClient()
    client.force_authenticate(user=user_fixture)
    return client


@pytest.fixture
def prometheus_registry(monkeypatch):
    """Substitui os counters globais por versões isoladas para inspeção."""
    registry = CollectorRegistry()

    created_total = Counter(
        "appointment_series_created_total",
        "Total number of series created",
        ["tenant_id", "status"],
        registry=registry,
    )
    size_total = Counter(
        "appointment_series_size_total",
        "Total number of appointments created per series",
        ["tenant_id"],
        registry=registry,
    )
    updated_total = Counter(
        "appointment_series_updated_total",
        "Total number of series update operations",
        ["tenant_id", "action", "status"],
        registry=registry,
    )
    occurrence_cancel_total = Counter(
        "appointment_series_occurrence_cancel_total",
        "Total number of single occurrence cancellations in series",
        ["tenant_id", "status"],
        registry=registry,
    )

    monkeypatch.setattr(series_views, "APPOINTMENT_SERIES_CREATED_TOTAL", created_total)
    monkeypatch.setattr(series_views, "APPOINTMENT_SERIES_SIZE_TOTAL", size_total)
    monkeypatch.setattr(series_views, "APPOINTMENT_SERIES_UPDATED_TOTAL", updated_total)
    monkeypatch.setattr(
        series_views,
        "APPOINTMENT_SERIES_OCCURRENCE_CANCEL_TOTAL",
        occurrence_cancel_total,
    )

    return registry


def _metric_value(counter, **labels):
    samples = list(counter.collect()[0].samples)
    for sample in samples:
        if all(sample.labels.get(k) == str(v) for k, v in labels.items()):
            return sample.value
    return 0


@pytest.mark.django_db
def test_series_creation_metrics(api_client, user_fixture, prometheus_registry):
    tenant_id = str(user_fixture.tenant_id)

    service = Service.objects.create(
        user=user_fixture, name="Serviço Teste", price_eur=35, duration_minutes=30
    )
    professional = Professional.objects.create(user=user_fixture, name="Clara")

    slots = []
    for day in (1, 2, 3):
        slot = ScheduleSlot.objects.create(
            professional=professional,
            start_time=timezone.now() + timedelta(days=day),
            end_time=timezone.now() + timedelta(days=day, minutes=30),
        )
        slots.append(slot)

    payload = {
        "service_id": service.id,
        "professional_id": professional.id,
        "appointments": [{"slot_id": slot.id} for slot in slots],
    }

    response = api_client.post("/api/appointments/series/", payload, format="json")
    assert response.status_code == 201

    assert _metric_value(
        series_views.APPOINTMENT_SERIES_CREATED_TOTAL,
        tenant_id=tenant_id,
        status="success",
    ) == 1
    assert _metric_value(
        series_views.APPOINTMENT_SERIES_SIZE_TOTAL,
        tenant_id=tenant_id,
    ) == len(slots)


@pytest.mark.django_db
def test_series_update_metrics(api_client, user_fixture, prometheus_registry):
    tenant_id = str(user_fixture.tenant_id)

    service = Service.objects.create(
        user=user_fixture, name="Serviço", price_eur=20, duration_minutes=30
    )
    professional = Professional.objects.create(user=user_fixture, name="Ana")

    slot = ScheduleSlot.objects.create(
        professional=professional,
        start_time=timezone.now() + timedelta(days=1),
        end_time=timezone.now() + timedelta(days=1, minutes=30),
    )

    create_payload = {
        "service_id": service.id,
        "professional_id": professional.id,
        "appointments": [{"slot_id": slot.id}],
    }
    response = api_client.post("/api/appointments/series/", create_payload, format="json")
    assert response.status_code == 201
    series_id = response.json()["series_id"]

    update_payload = {"action": "cancel_all"}
    response = api_client.patch(
        f"/api/appointments/series/{series_id}/",
        update_payload,
        format="json",
    )
    assert response.status_code == 200

    assert _metric_value(
        series_views.APPOINTMENT_SERIES_UPDATED_TOTAL,
        tenant_id=tenant_id,
        action="cancel_all",
        status="success",
    ) == 1


@pytest.mark.django_db
def test_series_occurrence_cancel_metrics(api_client, user_fixture, prometheus_registry):
    tenant_id = str(user_fixture.tenant_id)

    service = Service.objects.create(
        user=user_fixture, name="Serviço", price_eur=20, duration_minutes=30
    )
    professional = Professional.objects.create(user=user_fixture, name="Bruno")
    slot = ScheduleSlot.objects.create(
        professional=professional,
        start_time=timezone.now() + timedelta(days=1),
        end_time=timezone.now() + timedelta(days=1, minutes=30),
    )
    slot.mark_booked()

    series = AppointmentSeries.objects.create(
        tenant=user_fixture.tenant,
        client=user_fixture,
        service=service,
        professional=professional,
    )
    appointment = Appointment.objects.create(
        client=user_fixture,
        service=service,
        professional=professional,
        slot=slot,
        series=series,
    )

    response = api_client.post(
        f"/api/appointments/series/{series.id}/occurrence/{appointment.id}/cancel/",
        format="json",
    )
    assert response.status_code == 200

    assert _metric_value(
        series_views.APPOINTMENT_SERIES_OCCURRENCE_CANCEL_TOTAL,
        tenant_id=tenant_id,
        status="success",
    ) == 1
