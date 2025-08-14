# payments/tests/test_payments_stripe.py
import json
import pytest
from django.urls import reverse
from rest_framework.test import APIClient
from users.models import CustomUser
from payments.models import PaymentCustomer, Subscription


@pytest.fixture
def auth_client(db):
    def _make(user=None):
        if user is None:
            user = CustomUser.objects.create_user(
                username="u", email="u@example.com", password="pass"
            )
        c = APIClient()
        c.force_authenticate(user=user)
        return c, user

    return _make


# ---------- helpers de mocks ----------
class _StripeCheckoutSession:
    @staticmethod
    def create(**kwargs):
        # retorna objeto com url simulada
        return type("Obj", (), {"url": "https://stripe.test/checkout/sess_123"})


class _StripeBillingPortalSession:
    @staticmethod
    def create(**kwargs):
        return type("Obj", (), {"url": "https://stripe.test/portal/bps_123"})


class _StripeCustomer:
    @staticmethod
    def create(**kwargs):
        # devolve algo com id de customer
        return {"id": "cus_test_123"}


class _StripeWebhook:
    @staticmethod
    def construct_event(payload, sig_header, secret):
        return json.loads(payload)  # devolve o objeto do evento


class _StripeSDK:
    # namespaces usados pelo código
    checkout = type("checkout", (), {"Session": _StripeCheckoutSession})
    billing_portal = type(
        "billing_portal", (), {"Session": _StripeBillingPortalSession}
    )
    Customer = _StripeCustomer
    Webhook = _StripeWebhook


# ---------- testes ----------
@pytest.mark.django_db
def test_create_checkout_session_monthly(monkeypatch, settings, auth_client):
    # configura settings mínimos
    settings.STRIPE_API_KEY = "sk_test_xxx"
    settings.STRIPE_PRICE_MONTHLY = "price_monthly_123"
    settings.STRIPE_PRICE_YEARLY = "price_yearly_123"
    settings.FRONTEND_BASE_URL = "http://localhost:5173"
    settings.STRIPE_API_VERSION = "2024-06-20"

    # faz get_stripe() retornar nosso SDK falso
    from payments import stripe_utils

    monkeypatch.setattr(stripe_utils, "get_stripe", lambda: _StripeSDK)

    c, user = auth_client()
    url = "/api/payments/stripe/create-checkout-session/"
    resp = c.post(url, {"plan": "monthly"}, format="json")
    assert resp.status_code == 200
    assert resp.data["checkout_url"].startswith("https://stripe.test/checkout/")
    # cria/amarra customer
    pc = PaymentCustomer.objects.get(user=user)
    assert pc.stripe_customer_id == "cus_test_123"


@pytest.mark.django_db
def test_billing_portal_session(monkeypatch, settings, auth_client):
    settings.STRIPE_API_KEY = "sk_test_xxx"
    settings.FRONTEND_BASE_URL = "http://localhost:5173"
    settings.STRIPE_API_VERSION = "2024-06-20"

    from payments import stripe_utils

    monkeypatch.setattr(stripe_utils, "get_stripe", lambda: _StripeSDK)

    c, user = auth_client()
    url = "/api/payments/stripe/billing-portal/"
    resp = c.post(url, {}, format="json")
    assert resp.status_code == 200
    assert resp.data["portal_url"].startswith("https://stripe.test/portal/")
    assert PaymentCustomer.objects.filter(
        user=user, stripe_customer_id="cus_test_123"
    ).exists()


@pytest.mark.django_db
def test_webhook_checkout_session_completed_creates_subscription(
    monkeypatch, settings, auth_client
):
    settings.STRIPE_API_KEY = "sk_test_xxx"
    settings.STRIPE_WEBHOOK_SECRET = "whsec_test"
    settings.STRIPE_API_VERSION = "2024-06-20"

    # constrói customer local
    c, user = auth_client()
    pc = PaymentCustomer.objects.create(user=user, stripe_customer_id="cus_test_123")

    # mocka stripe.Webhook.construct_event
    from payments import views as payments_views

    monkeypatch.setattr(payments_views, "stripe", _StripeSDK)

    # evento simulando checkout.session.completed
    payload = json.dumps(
        {
            "type": "checkout.session.completed",
            "data": {
                "object": {
                    "customer": "cus_test_123",
                    "subscription": "sub_abc",
                }
            },
        }
    )
    # a view só precisa do header/secret para passar na validação mockada
    sig = "t=0,v1=deadbeef"

    url = "/api/payments/stripe/webhook/"
    resp = c.post(
        url, data=payload, content_type="application/json", HTTP_STRIPE_SIGNATURE=sig
    )
    assert resp.status_code == 200

    sub = Subscription.objects.get(user=user)
    assert sub.stripe_subscription_id == "sub_abc"
