import json
import itertools
import pytest
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from users.models import CommLedger


class _StripeWebhook:
    @staticmethod
    def construct_event(payload, sig_header, secret):
        # Para testes, apenas retorna o objeto do evento
        return json.loads(payload)


@pytest.fixture
def auth_client(db):
    from users.models import CustomUser

    def _make(user=None):
        if user is None:
            user = CustomUser.objects.create_user(
                username="sse_purchase_user",
                email="sse_purchase_user@example.com",
                password="pass",
            )
        c = APIClient()
        c.force_authenticate(user=user)
        return c, user

    return _make


@pytest.mark.django_db
def test_smoke_compra_emite_credit_update_com_ledger(
    auth_client, monkeypatch, settings
):
    """
    BE-CRED-04 (2.2): Smoke E2E de compra deve emitir credit_update com ledger no SSE.
    """
    # Evitar espera no loop do SSE
    monkeypatch.setattr("users.views.time.sleep", lambda s: None)

    # Garantir secret de webhook definido
    settings.STRIPE_WEBHOOK_SECRET = "whsec_test_smoke"

    # Configurar price IDs de créditos para o ambiente de teste (CI não usa .env)
    settings.STRIPE_PRICE_CREDITS_5_ID = "price_credits_5_test"
    settings.STRIPE_PRICE_CREDITS_10_ID = "price_credits_10_test"
    settings.STRIPE_PRICE_CREDITS_25_ID = "price_credits_25_test"
    settings.STRIPE_PRICE_CREDITS_50_ID = "price_credits_50_test"
    settings.STRIPE_PRICE_CREDITS_100_ID = "price_credits_100_test"

    # Ajustar o mapa estático de PRICE_TO_CREDITS para refletir os price IDs de teste
    from decimal import Decimal
    from payments.services import CreditPurchaseService
    monkeypatch.setattr(
        CreditPurchaseService,
        "PRICE_TO_CREDITS",
        {
            settings.STRIPE_PRICE_CREDITS_5_ID: Decimal("5.00"),
            settings.STRIPE_PRICE_CREDITS_10_ID: Decimal("10.00"),
            settings.STRIPE_PRICE_CREDITS_25_ID: Decimal("25.00"),
            settings.STRIPE_PRICE_CREDITS_50_ID: Decimal("50.00"),
            settings.STRIPE_PRICE_CREDITS_100_ID: Decimal("100.00"),
        },
        raising=True,
    )

    # Patching do Stripe SDK (PaymentIntent/Customer) e Webhook
    import payments.services as payments_services
    import payments.stripe_utils as stripe_utils
    import payments.webhooks as payments_webhooks

    class _StripePaymentIntent:
        last_kwargs = None

        @staticmethod
        def create(**kwargs):
            _StripePaymentIntent.last_kwargs = kwargs
            return type("PaymentIntentObj", (), {
                "client_secret": "pi_secret_test_123",
                "id": "pi_test_123",
                "amount": kwargs.get("amount", 0),
                "currency": kwargs.get("currency", "eur"),
            })

    class _StripeCustomer:
        @staticmethod
        def create(**kwargs):
            return {"id": "cus_test_smoke_credits"}

    class _StripeSDK:
        PaymentIntent = _StripePaymentIntent
        Customer = _StripeCustomer
        Webhook = _StripeWebhook

    monkeypatch.setattr(payments_services, "stripe", _StripeSDK, raising=True)
    monkeypatch.setattr(stripe_utils, "get_stripe", lambda: _StripeSDK, raising=True)
    monkeypatch.setattr(payments_webhooks, "stripe", _StripeSDK, raising=True)

    client, user = auth_client()

    # Abre stream SSE
    sse_url = reverse("realtime_credits")
    resp_stream = client.get(sse_url)
    assert resp_stream.status_code == status.HTTP_200_OK
    stream = resp_stream.streaming_content

    # Consumir eventos iniciais (estado + heartbeat)
    _ = list(itertools.islice(stream, 2))

    # Criar PaymentIntent de compra de créditos (5 EUR)
    purchase_url = "/api/payments/stripe/credits/purchase/"
    resp_pi = client.post(purchase_url, {"amount_eur": 5.0}, format="json")
    assert resp_pi.status_code == status.HTTP_200_OK
    payment_intent_id = resp_pi.data["payment_intent_id"]

    # Simular webhook de sucesso do PaymentIntent
    webhook_url = "/api/payments/stripe/webhook/"
    event_payload = {
        "id": "evt_test_pi_succeeded",
        "type": "payment_intent.succeeded",
        "data": {"object": {"id": payment_intent_id}},
    }
    resp_webhook = client.post(
        webhook_url,
        data=json.dumps(event_payload),
        content_type="application/json",
    )
    assert resp_webhook.status_code == status.HTTP_200_OK

    # Garantir que ledger de purchase foi criado para o tenant
    assert CommLedger.objects.filter(
        tenant=user.tenant, transaction_type=CommLedger.TransactionType.PURCHASE
    ).exists()

    def _decode(chunk: bytes) -> str:
        try:
            return chunk.decode("utf-8")
        except Exception:
            return str(chunk)

    # Ler até encontrar credit_update que contenha "ledger" de tipo purchase
    found = False
    for _ in range(200):
        try:
            chunk = next(stream)
        except StopIteration:
            break
        text = _decode(chunk)
        if (
            "event: credit_update" in text
            and "\"ledger\"" in text
            and "\"type\": \"purchase\"" in text
        ):
            found = True
            break

    assert found, "Não foi emitido evento de ledger (purchase) após compra (smoke)"