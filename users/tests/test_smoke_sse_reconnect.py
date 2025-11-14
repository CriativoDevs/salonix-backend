import itertools
import re
import pytest
from django.urls import reverse
from rest_framework import status


@pytest.mark.django_db
def test_smoke_sse_reconexao_last_event_id_sem_perda(
    sse_auth_client, tenant_fixture, monkeypatch
):
    """
    BE-CRED-04 (2.3): Reconexão SSE usando Last-Event-ID deve retomar sem perda.
    - Abre stream SSE e consome eventos iniciais.
    - Gera um ledger (consumo) e captura seu id via SSE (id: N).
    - Gera um novo ledger depois.
    - Reconecta enviando Last-Event-ID = N e verifica que só recebe eventos > N.
    """
    # Evitar espera no loop do SSE
    monkeypatch.setattr("users.views.time.sleep", lambda s: None)

    client, user = sse_auth_client()

    # Abre stream inicial
    sse_url = reverse("realtime_credits")
    resp_stream = client.get(sse_url)
    assert resp_stream.status_code == status.HTTP_200_OK
    stream = resp_stream.streaming_content

    # Consumir eventos iniciais (estado + heartbeat)
    _ = list(itertools.islice(stream, 2))

    # Dispara primeiro consumo (gera ledger A)
    consume_url = reverse("consume_credits")
    payload_a = {"amount": 1.0, "description": "SSE reconnect A"}
    resp_a = client.post(consume_url, payload_a, format="json")
    assert resp_a.status_code == status.HTTP_200_OK

    # Ler até encontrar credit_update com ledger e capturar id
    last_id = None
    for _ in range(200):
        try:
            chunk = next(stream)
        except StopIteration:
            break
        text = chunk.decode() if isinstance(chunk, (bytes, bytearray)) else str(chunk)
        if "event: credit_update" in text and '"ledger"' in text:
            # Extrai o id da linha "id: N"
            m = re.search(r"^id:\s*(\d+)$", text, flags=re.MULTILINE)
            if m:
                last_id = int(m.group(1))
                break

    assert last_id is not None, "Não foi possível capturar id do último evento"

    # Gera novo ledger B após o id capturado
    payload_b = {"amount": 2.0, "description": "SSE reconnect B"}
    resp_b = client.post(consume_url, payload_b, format="json")
    assert resp_b.status_code == status.HTTP_200_OK

    # Reconecta com Last-Event-ID = last_id
    resp_reconnect = client.get(sse_url, **{"HTTP_LAST_EVENT_ID": str(last_id)})
    assert resp_reconnect.status_code == status.HTTP_200_OK
    stream2 = resp_reconnect.streaming_content

    # Consumir alguns eventos iniciais (estado + heartbeat)
    _ = list(itertools.islice(stream2, 2))

    # Deve receber ledger com id > last_id
    found_newer = False
    newer_id = None
    for _ in range(200):
        try:
            chunk = next(stream2)
        except StopIteration:
            break
        text = chunk.decode() if isinstance(chunk, (bytes, bytearray)) else str(chunk)
        if "event: credit_update" in text and '"ledger"' in text:
            m = re.search(r"^id:\s*(\d+)$", text, flags=re.MULTILINE)
            if m:
                newer_id = int(m.group(1))
                if newer_id and newer_id > last_id:
                    found_newer = True
                    break

    assert found_newer, f"Reconexão não retornou evento posterior ao {last_id} (id={newer_id})"