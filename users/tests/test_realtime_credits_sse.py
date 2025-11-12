import json
import itertools
import pytest
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient
from users.models import CommLedger
from users.observability import USERS_SSE_EVENTS_TOTAL


@pytest.mark.django_db
class TestRealtimeCreditsSSE:
    def setup_method(self):
        self.client = APIClient()

    def _decode_chunk(self, chunk):
        return chunk.decode() if isinstance(chunk, (bytes, bytearray)) else str(chunk)

    def test_sse_requires_auth(self):
        url = reverse("realtime_credits")
        response = self.client.get(url)
        assert response.status_code in {status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN}

    def test_sse_initial_events(self, user_fixture, monkeypatch):
        # Evitar espera no loop do SSE
        monkeypatch.setattr("users.views.time.sleep", lambda s: None)

        self.client.force_authenticate(user=user_fixture)

        url = reverse("realtime_credits")
        response = self.client.get(url)
        assert response.status_code == status.HTTP_200_OK

        stream = response.streaming_content
        first_two = list(itertools.islice(stream, 2))
        assert len(first_two) == 2

        first = self._decode_chunk(first_two[0])
        second = self._decode_chunk(first_two[1])

        assert "event: credit_update" in first
        assert "event: heartbeat" in second

    def test_sse_emits_on_consume(self, user_fixture, tenant_fixture, monkeypatch):
        # Evitar espera no loop do SSE
        monkeypatch.setattr("users.views.time.sleep", lambda s: None)

        self.client.force_authenticate(user=user_fixture)

        # Abre o stream
        sse_url = reverse("realtime_credits")
        response = self.client.get(sse_url)
        assert response.status_code == status.HTTP_200_OK

        stream = response.streaming_content

        # Consumir os dois primeiros eventos (estado inicial + heartbeat)
        _ = list(itertools.islice(stream, 2))

        # Dispara uma transação de consumo de créditos (gera item no ledger)
        consume_url = reverse("consume_credits")
        payload = {"amount": 1.0, "description": "Teste consumo SSE"}
        resp_consume = self.client.post(consume_url, payload, format="json")
        assert resp_consume.status_code == status.HTTP_200_OK

        # Lê o stream até encontrar um credit_update com ledger
        # Garantir que o ledger foi criado
        assert CommLedger.objects.filter(tenant=tenant_fixture).exists()

        found_ledger_event = False
        for _ in range(100):
            try:
                chunk = next(stream)
            except StopIteration:
                break
            text = self._decode_chunk(chunk)
            if "event: credit_update" in text and "\"ledger\"" in text:
                found_ledger_event = True
                break

        assert found_ledger_event, "Não foi emitido evento de ledger após consumo"

    @pytest.mark.django_db
    def test_sse_metrics_heartbeat_and_update(self, user_fixture, monkeypatch):
        monkeypatch.setattr("users.views.time.sleep", lambda s: None)

        self.client.force_authenticate(user=user_fixture)

        hb_before = USERS_SSE_EVENTS_TOTAL.labels(event="heartbeat", result="emitted")._value.get()
        cu_before = USERS_SSE_EVENTS_TOTAL.labels(event="credit_update", result="emitted")._value.get()

        url = reverse("realtime_credits")
        response = self.client.get(url)
        assert response.status_code == status.HTTP_200_OK

        stream = response.streaming_content
        _ = list(itertools.islice(stream, 2))

        hb_after = USERS_SSE_EVENTS_TOTAL.labels(event="heartbeat", result="emitted")._value.get()
        cu_after = USERS_SSE_EVENTS_TOTAL.labels(event="credit_update", result="emitted")._value.get()

        assert hb_after >= hb_before + 1
        assert cu_after >= cu_before + 1

    @pytest.mark.django_db
    def test_sse_metrics_error(self, user_fixture, monkeypatch):
        monkeypatch.setattr("users.views.time.sleep", lambda s: None)

        self.client.force_authenticate(user=user_fixture)

        err_before = USERS_SSE_EVENTS_TOTAL.labels(event="error", result="emitted")._value.get()
        hb_before = USERS_SSE_EVENTS_TOTAL.labels(event="heartbeat", result="emitted")._value.get()

        url = reverse("realtime_credits")

        def _boom(*args, **kwargs):
            raise RuntimeError("ledger error")

        monkeypatch.setattr("users.views.CommLedger.objects.filter", _boom)

        response = self.client.get(url)
        assert response.status_code == status.HTTP_200_OK

        stream = response.streaming_content
        _ = list(itertools.islice(stream, 3))

        err_after = USERS_SSE_EVENTS_TOTAL.labels(event="error", result="emitted")._value.get()
        hb_after = USERS_SSE_EVENTS_TOTAL.labels(event="heartbeat", result="emitted")._value.get()

        assert err_after >= err_before + 1
        assert hb_after >= hb_before + 1