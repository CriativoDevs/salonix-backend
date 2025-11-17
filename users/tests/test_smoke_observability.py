import itertools
from unittest.mock import patch

import pytest
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from users.observability import USERS_SSE_EVENTS_TOTAL


@pytest.mark.django_db
def test_smoke_sse_metrics_min_increment(user_fixture, monkeypatch):
    """
    OBS-3.1: Verifica incremento mínimo de métricas SSE (heartbeat e credit_update).
    """
    # Evitar espera no loop do SSE
    monkeypatch.setattr("users.views.time.sleep", lambda s: None)

    client = APIClient()
    client.force_authenticate(user=user_fixture)

    hb_before = USERS_SSE_EVENTS_TOTAL.labels(
        event="heartbeat", result="emitted"
    )._value.get()
    cu_before = USERS_SSE_EVENTS_TOTAL.labels(
        event="credit_update", result="emitted"
    )._value.get()

    url = reverse("realtime_credits")
    response = client.get(url)
    assert response.status_code == status.HTTP_200_OK

    stream = response.streaming_content
    _ = list(itertools.islice(stream, 2))

    hb_after = USERS_SSE_EVENTS_TOTAL.labels(
        event="heartbeat", result="emitted"
    )._value.get()
    cu_after = USERS_SSE_EVENTS_TOTAL.labels(
        event="credit_update", result="emitted"
    )._value.get()

    assert hb_after >= hb_before + 1
    assert cu_after >= cu_before + 1


@pytest.mark.django_db
def test_smoke_sse_x_request_id_headers_and_logs(user_fixture, monkeypatch):
    """
    OBS-3.2: Confirma X-Request-ID propagado em headers e presente nos logs do fluxo SSE.
    """
    monkeypatch.setattr("users.views.time.sleep", lambda s: None)

    client = APIClient()
    client.force_authenticate(user=user_fixture)

    sse_url = reverse("realtime_credits")
    req_id = "smoke-req-123"

    with patch("salonix_backend.middleware.logger") as mock_logger:
        response = client.get(sse_url, HTTP_X_REQUEST_ID=req_id)

    assert response.status_code == status.HTTP_200_OK
    assert response["X-Request-ID"] == req_id

    # Verificar pelo menos log de início do request com o request_id propagado
    assert mock_logger.info.call_count >= 1
    started_calls = [
        call
        for call in mock_logger.info.call_args_list
        if "Request started" in call[0][0]
    ]
    assert len(started_calls) >= 1
    assert started_calls[0][1]["extra"]["request_id"] == req_id
