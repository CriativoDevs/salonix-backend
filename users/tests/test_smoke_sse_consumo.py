import itertools
import pytest
from django.urls import reverse
from rest_framework import status

from users.models import CommLedger


@pytest.mark.django_db
def test_smoke_consumo_emite_credit_update_com_ledger(
    sse_auth_client, monkeypatch, configure_credit_prices
):
    """
    BE-CRED-04 (2.1): Smoke E2E de consumo deve emitir credit_update com ledger no SSE.
    """
    # Evitar espera no loop do SSE
    monkeypatch.setattr("users.views.time.sleep", lambda s: None)

    client, user = sse_auth_client()

    # Abre stream SSE
    sse_url = reverse("realtime_credits")
    resp_stream = client.get(sse_url)
    assert resp_stream.status_code == status.HTTP_200_OK

    stream = resp_stream.streaming_content

    # Consumir eventos iniciais (estado + heartbeat)
    _ = list(itertools.islice(stream, 2))

    # Dispara consumo de créditos (gera item no ledger)
    consume_url = reverse("consume_credits")
    payload = {"amount": 1.0, "description": "Smoke consumo SSE"}
    resp_consume = client.post(consume_url, payload, format="json")
    assert resp_consume.status_code == status.HTTP_200_OK

    # Garantir que ledger foi criado para o tenant
    assert CommLedger.objects.filter(tenant=user.tenant).exists()

    def _decode(chunk: bytes) -> str:
        try:
            return chunk.decode("utf-8")
        except Exception:
            return str(chunk)

    # Ler até encontrar credit_update que contenha "ledger"
    found = False
    for _ in range(200):
        try:
            chunk = next(stream)
        except StopIteration:
            break
        text = _decode(chunk)
        if "event: credit_update" in text and "\"ledger\"" in text:
            found = True
            break

    assert found, "Não foi emitido evento de ledger após consumo (smoke)"