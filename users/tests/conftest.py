"""
Fixtures de preparação para smoke tests SSE de créditos (BE-CRED-04 - item 1).

Inclui:
- Cliente autenticado rápido
- Mock do Stripe SDK para PaymentIntent/Customer
- Configuração de preços de créditos (settings + mapa do serviço)
"""

import pytest
from decimal import Decimal
from rest_framework.test import APIClient


@pytest.fixture
def sse_auth_client(db):
    """Factory de APIClient autenticado (tenant padrão vem do conftest global)."""
    from users.models import CustomUser

    def _make(user=None):
        if user is None:
            user = CustomUser.objects.create_user(
                username="sse_user",
                email="sse_user@example.com",
                password="pass",
            )

        client = APIClient()
        client.force_authenticate(user=user)
        return client, user

    return _make


# ---------- Stripe mock SDK ----------
class _StripePaymentIntent:
    last_kwargs = None

    @staticmethod
    def create(**kwargs):
        _StripePaymentIntent.last_kwargs = kwargs
        # objeto mínimo com client_secret e id
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


@pytest.fixture
def stripe_mock(monkeypatch):
    """Mocka o Stripe utilizado pelos serviços de pagamentos e utilitários."""
    # payments.services importa "stripe" no topo; substituímos por nosso SDK
    import payments.services as payments_services
    monkeypatch.setattr(payments_services, "stripe", _StripeSDK, raising=True)

    # Também garantir que get_stripe() dos utils devolva nosso SDK
    import payments.stripe_utils as stripe_utils
    monkeypatch.setattr(stripe_utils, "get_stripe", lambda: _StripeSDK, raising=True)

    return _StripeSDK


@pytest.fixture
def configure_credit_prices(settings, monkeypatch):
    """Configura preços de crédito e ajusta o mapa do CreditPurchaseService.

    Evita dependência de .env real e garante mapeamento estável para os smoke tests.
    """
    # Definir price IDs de teste
    settings.STRIPE_PRICE_CREDITS_5_ID = "price_credits_5_test"
    settings.STRIPE_PRICE_CREDITS_10_ID = "price_credits_10_test"
    settings.STRIPE_PRICE_CREDITS_25_ID = "price_credits_25_test"
    settings.STRIPE_PRICE_CREDITS_50_ID = "price_credits_50_test"
    settings.STRIPE_PRICE_CREDITS_100_ID = "price_credits_100_test"

    # Patch do mapa estático do serviço pós-configuração
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

    return {
        "price_5": settings.STRIPE_PRICE_CREDITS_5_ID,
        "price_10": settings.STRIPE_PRICE_CREDITS_10_ID,
        "price_25": settings.STRIPE_PRICE_CREDITS_25_ID,
        "price_50": settings.STRIPE_PRICE_CREDITS_50_ID,
        "price_100": settings.STRIPE_PRICE_CREDITS_100_ID,
    }