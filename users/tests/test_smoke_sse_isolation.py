import itertools
from decimal import Decimal
import pytest
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from users.models import Tenant, CustomUser


@pytest.mark.django_db
def test_smoke_isolamento_por_tenant_sse(monkeypatch):
    """
    BE-CRED-04 (2.4): Verifica que eventos SSE não vazam entre tenants.
    - Abre dois streams SSE, um para cada tenant.
    - Gera ledger no Tenant A e confirma que o Tenant B não recebe evento com "ledger".
    """
    # Evitar espera no loop do SSE
    monkeypatch.setattr("users.views.time.sleep", lambda s: None)

    # Criar dois tenants e usuários distintos
    tenant_a = Tenant.objects.create(
        name="Tenant A",
        slug="tenant-a",
        comm_credit_eur=Decimal("50.00"),
    )
    tenant_b = Tenant.objects.create(
        name="Tenant B",
        slug="tenant-b",
        comm_credit_eur=Decimal("50.00"),
    )

    user_a = CustomUser.objects.create_user(
        username="user_a", email="a@example.com", password="Pass1234!"
    )
    user_b = CustomUser.objects.create_user(
        username="user_b", email="b@example.com", password="Pass1234!"
    )
    # Associar explicitamente cada usuário ao seu tenant
    user_a.tenant = tenant_a
    user_a.save(update_fields=["tenant"])
    user_b.tenant = tenant_b
    user_b.save(update_fields=["tenant"])

    client_a = APIClient()
    client_b = APIClient()
    client_a.force_authenticate(user=user_a)
    client_b.force_authenticate(user=user_b)

    # Abre streams SSE
    sse_url = reverse("realtime_credits")
    resp_a = client_a.get(sse_url)
    resp_b = client_b.get(sse_url)
    assert resp_a.status_code == status.HTTP_200_OK
    assert resp_b.status_code == status.HTTP_200_OK

    stream_a = resp_a.streaming_content
    stream_b = resp_b.streaming_content

    # Consumir eventos iniciais (estado + heartbeat) de ambos
    _ = list(itertools.islice(stream_a, 2))
    _ = list(itertools.islice(stream_b, 2))

    # Dispara consumo de créditos apenas no Tenant A (gera item no ledger A)
    consume_url = reverse("consume_credits")
    payload = {"amount": 1.0, "description": "Isolamento Tenant A"}
    resp_consume_a = client_a.post(consume_url, payload, format="json")
    assert resp_consume_a.status_code == status.HTTP_200_OK

    # Ler stream A até encontrar evento de ledger
    found_ledger_a = False
    for _ in range(200):
        try:
            chunk = next(stream_a)
        except StopIteration:
            break
        text = chunk.decode() if isinstance(chunk, (bytes, bytearray)) else str(chunk)
        if "event: credit_update" in text and '"ledger"' in text:
            found_ledger_a = True
            break
    assert found_ledger_a, "Tenant A não recebeu evento de ledger após consumo"

    # Garantir que o stream B não recebe evento de ledger
    found_ledger_b = False
    for _ in range(200):
        try:
            chunk = next(stream_b)
        except StopIteration:
            break
        text = chunk.decode() if isinstance(chunk, (bytes, bytearray)) else str(chunk)
        if "event: credit_update" in text and '"ledger"' in text:
            found_ledger_b = True
            break

    assert not found_ledger_b, "Tenant B recebeu indevidamente evento de ledger do Tenant A"