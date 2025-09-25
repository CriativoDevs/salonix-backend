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
    last_kwargs = None

    @staticmethod
    def create(**kwargs):
        _StripeCheckoutSession.last_kwargs = kwargs
        return type("Obj", (), {"url": "https://stripe.test/checkout/sess_123"})


class _StripeBillingPortalSession:
    last_kwargs = None

    @staticmethod
    def create(**kwargs):
        _StripeBillingPortalSession.last_kwargs = kwargs
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


class _StripeSubscription:
    last_kwargs = None

    @staticmethod
    def retrieve(subscription_id, expand=None):
        _StripeSubscription.last_kwargs = {
            "subscription_id": subscription_id,
            "expand": expand,
        }
        return {
            "id": subscription_id,
            "status": "active",
            "cancel_at_period_end": False,
            "current_period_end": 1_725_897_200,
            "metadata": {"plan_code": "pro"},
            "items": {
                "data": [
                    {
                        "price": {
                            "id": "price_pro_123",
                            "recurring": {"interval": "month"},
                        }
                    }
                ]
            },
        }


class _StripeSDK:
    # namespaces usados pelo código
    checkout = type("checkout", (), {"Session": _StripeCheckoutSession})
    billing_portal = type(
        "billing_portal", (), {"Session": _StripeBillingPortalSession}
    )
    Customer = _StripeCustomer
    Webhook = _StripeWebhook
    Subscription = _StripeSubscription


# ---------- testes ----------
@pytest.mark.django_db
def test_create_checkout_session_basic_plan(monkeypatch, settings, auth_client):
    # configura settings mínimos
    settings.STRIPE_API_KEY = "sk_test_xxx"
    settings.STRIPE_PRICE_BASIC_MONTHLY_ID = "price_basic_123"
    settings.STRIPE_TRIAL_PERIOD_DAYS = 0
    settings.FRONTEND_BASE_URL = "http://localhost:5173"
    settings.STRIPE_API_VERSION = "2024-06-20"

    # faz get_stripe() retornar nosso SDK falso
    from payments import stripe_utils

    monkeypatch.setattr(stripe_utils, "get_stripe", lambda: _StripeSDK)

    c, user = auth_client()
    url = "/api/payments/stripe/create-checkout-session/"
    resp = c.post(url, {"plan": "basic"}, format="json")
    assert resp.status_code == 200
    assert resp.data["checkout_url"].startswith("https://stripe.test/checkout/")
    # cria/amarra customer
    pc = PaymentCustomer.objects.get(user=user)
    assert pc.stripe_customer_id == "cus_test_123"

    created_kwargs = _StripeCheckoutSession.last_kwargs
    assert created_kwargs["line_items"][0]["price"] == "price_basic_123"
    assert created_kwargs["metadata"]["plan_code"] == "basic"
    assert created_kwargs["subscription_data"]["metadata"]["plan_code"] == "basic"


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
    settings.STRIPE_PRICE_PRO_MONTHLY_ID = "price_pro_123"

    # constrói customer local
    c, user = auth_client()
    pc = PaymentCustomer.objects.create(user=user, stripe_customer_id="cus_test_123")

    # mocka stripe.Webhook.construct_event
    from payments import views as payments_views

    monkeypatch.setattr(payments_views, "stripe", _StripeSDK)
    from payments import stripe_utils as payments_stripe_utils

    assert payments_stripe_utils.get_plan_code_from_price("price_pro_123") == "pro"

    original_update_or_create = Subscription.objects.update_or_create
    update_calls = {}

    def _instrumented_update_or_create(*args, **kwargs):
        update_calls["called"] = True
        return original_update_or_create(*args, **kwargs)

    monkeypatch.setattr(
        Subscription.objects, "update_or_create", _instrumented_update_or_create
    )

    original_filter = payments_views.PaymentCustomer.objects.filter
    filter_meta = {}

    def _instrumented_filter(*args, **kwargs):
        qs = original_filter(*args, **kwargs)
        try:
            filter_meta["count"] = qs.count()
        except Exception:
            filter_meta["count"] = None
        return qs

    monkeypatch.setattr(
        payments_views.PaymentCustomer.objects, "filter", _instrumented_filter
    )

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
    assert _StripeSubscription.last_kwargs is not None
    assert filter_meta.get("count") == 1
    assert update_calls.get("called") is True

    sub = Subscription.objects.get(user=user)
    assert sub.stripe_subscription_id == "sub_abc"
    assert sub.price_id == "price_pro_123"

    flags = user.featureflags
    flags.refresh_from_db()
    assert flags.is_pro is True
    assert flags.pro_plan == "pro"

    tenant = user.tenant
    tenant.refresh_from_db()
    assert tenant.plan_tier == "pro"
