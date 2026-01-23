# payments/tests/test_payments_stripe.py
import json
import pytest
from decimal import Decimal
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

    from users.models import Tenant, TenantStaffMember

    c, user = auth_client()
    tenant = Tenant.objects.create(name="T1", slug="t1")
    user.tenant = tenant
    user.save()
    TenantStaffMember.objects.create(
        tenant=tenant,
        user=user,
        role=TenantStaffMember.Role.OWNER,
        status=TenantStaffMember.Status.ACTIVE,
    )
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
def test_checkout_trial_suppressed_for_existing_subscription(
    monkeypatch, settings, auth_client
):
    settings.STRIPE_API_KEY = "sk_test_xxx"
    settings.STRIPE_PRICE_STANDARD_MONTHLY_ID = "price_standard_123"
    settings.STRIPE_TRIAL_PERIOD_DAYS = 14
    settings.FRONTEND_BASE_URL = "http://localhost:5173"
    settings.STRIPE_API_VERSION = "2024-06-20"

    from payments import stripe_utils

    monkeypatch.setattr(stripe_utils, "get_stripe", lambda: _StripeSDK)

    from users.models import Tenant, TenantStaffMember

    c, user = auth_client()
    tenant = Tenant.objects.create(name="T2", slug="t2")
    user.tenant = tenant
    user.save()
    TenantStaffMember.objects.create(
        tenant=tenant,
        user=user,
        role=TenantStaffMember.Role.OWNER,
        status=TenantStaffMember.Status.ACTIVE,
    )

    Subscription.objects.create(
        user=user,
        stripe_subscription_id="sub_existing_123",
        status="active",
    )

    url = "/api/payments/stripe/create-checkout-session/"
    resp = c.post(url, {"plan": "standard"}, format="json")
    assert resp.status_code == 200

    created_kwargs = _StripeCheckoutSession.last_kwargs
    assert created_kwargs["line_items"][0]["price"] == "price_standard_123"
    assert "trial_period_days" not in created_kwargs["subscription_data"]


@pytest.mark.django_db
def test_checkout_trial_suppressed_for_other_user_in_same_tenant(
    monkeypatch, settings, auth_client
):
    settings.STRIPE_API_KEY = "sk_test_xxx"
    settings.STRIPE_PRICE_STANDARD_MONTHLY_ID = "price_standard_123"
    settings.STRIPE_TRIAL_PERIOD_DAYS = 14
    settings.FRONTEND_BASE_URL = "http://localhost:5173"
    settings.STRIPE_API_VERSION = "2024-06-20"

    from payments import stripe_utils

    monkeypatch.setattr(stripe_utils, "get_stripe", lambda: _StripeSDK)

    from users.models import Tenant, TenantStaffMember

    c, owner = auth_client()
    tenant = Tenant.objects.create(name="T4", slug="t4")
    owner.tenant = tenant
    owner.save()
    TenantStaffMember.objects.create(
        tenant=tenant,
        user=owner,
        role=TenantStaffMember.Role.OWNER,
        status=TenantStaffMember.Status.ACTIVE,
    )

    other = CustomUser.objects.create_user(
        username="other",
        email="other@test.com",
        password="pass",
        tenant=tenant,
    )

    Subscription.objects.create(
        user=other,
        stripe_subscription_id="sub_existing_tenant_123",
        status="active",
    )

    url = "/api/payments/stripe/create-checkout-session/"
    resp = c.post(url, {"plan": "standard"}, format="json")
    assert resp.status_code == 200

    created_kwargs = _StripeCheckoutSession.last_kwargs
    assert created_kwargs["line_items"][0]["price"] == "price_standard_123"
    assert "trial_period_days" not in created_kwargs["subscription_data"]
    assert created_kwargs["subscription_data"].get("trial_from_plan") is False


@pytest.mark.django_db
def test_checkout_trial_applied_for_new_customer(monkeypatch, settings, auth_client):
    settings.STRIPE_API_KEY = "sk_test_xxx"
    settings.STRIPE_PRICE_PRO_MONTHLY_ID = "price_pro_123"
    settings.STRIPE_TRIAL_PERIOD_DAYS = 14
    settings.FRONTEND_BASE_URL = "http://localhost:5173"
    settings.STRIPE_API_VERSION = "2024-06-20"

    from payments import stripe_utils

    monkeypatch.setattr(stripe_utils, "get_stripe", lambda: _StripeSDK)

    from users.models import Tenant, TenantStaffMember

    c, user = auth_client()
    tenant = Tenant.objects.create(name="T3", slug="t3")
    user.tenant = tenant
    user.save()
    TenantStaffMember.objects.create(
        tenant=tenant,
        user=user,
        role=TenantStaffMember.Role.OWNER,
        status=TenantStaffMember.Status.ACTIVE,
    )
    url = "/api/payments/stripe/create-checkout-session/"
    resp = c.post(url, {"plan": "pro"}, format="json")
    assert resp.status_code == 200

    created_kwargs = _StripeCheckoutSession.last_kwargs
    assert created_kwargs["line_items"][0]["price"] == "price_pro_123"
    assert created_kwargs["subscription_data"].get("trial_period_days") == 14


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
    PaymentCustomer.objects.create(user=user, stripe_customer_id="cus_test_123")

    # mocka stripe.Webhook.construct_event
    from payments import views as payments_views
    from payments import webhooks as payments_webhooks

    monkeypatch.setattr(payments_views, "stripe", _StripeSDK)
    monkeypatch.setattr(payments_webhooks, "stripe", _StripeSDK)
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
            "id": "evt_test_123",
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


@pytest.mark.django_db
def test_checkout_requires_owner_role(monkeypatch, settings):
    settings.STRIPE_API_KEY = "sk_test_xxx"
    settings.STRIPE_PRICE_STANDARD_MONTHLY_ID = "price_standard_123"
    settings.STRIPE_TRIAL_PERIOD_DAYS = 14
    settings.FRONTEND_BASE_URL = "http://localhost:5173"
    settings.STRIPE_API_VERSION = "2024-06-20"

    from payments import stripe_utils
    from users.models import Tenant, CustomUser, TenantStaffMember

    monkeypatch.setattr(stripe_utils, "get_stripe", lambda: _StripeSDK)

    tenant = Tenant.objects.create(name="T", slug="t")

    # Usuário manager, não OWNER
    user = CustomUser.objects.create_user(
        username="mgr",
        email="mgr@test.com",
        password="pass",
        tenant=tenant,
    )
    TenantStaffMember.objects.create(
        tenant=tenant,
        user=user,
        role=TenantStaffMember.Role.MANAGER,
        status=TenantStaffMember.Status.ACTIVE,
    )

    c = APIClient()
    c.force_authenticate(user=user)

    url = "/api/payments/stripe/create-checkout-session/"
    resp = c.post(url, {"plan": "standard"}, format="json")
    assert resp.status_code == 403
    assert "Somente OWNER" in resp.data.get("detail", "")


@pytest.mark.django_db
def test_webhook_invoice_payment_succeeded_applies_included_credits(
    monkeypatch, settings, auth_client
):
    settings.STRIPE_API_KEY = "sk_test_xxx"
    settings.STRIPE_WEBHOOK_SECRET = "whsec_test"
    settings.STRIPE_API_VERSION = "2024-06-20"
    settings.STRIPE_PRICE_PRO_MONTHLY_ID = "price_pro_123"

    from payments import views as payments_views
    from payments import stripe_utils as payments_stripe_utils
    from users.models import Tenant, CommLedger

    monkeypatch.setattr(payments_views, "stripe", _StripeSDK)

    c, user = auth_client()
    tenant = Tenant.objects.create(name="TB", slug="tb")
    # Resetar créditos e ledger causados pelo signal para garantir estado limpo
    Tenant.objects.filter(pk=tenant.pk).update(comm_credit_eur=Decimal("0.00"))
    tenant.comm_ledger.all().delete()
    tenant.refresh_from_db()

    user.tenant = tenant
    user.save()
    PaymentCustomer.objects.create(user=user, stripe_customer_id="cus_test_123")

    assert payments_stripe_utils.get_plan_code_from_price("price_pro_123") == "pro"

    payload1 = json.dumps(
        {
            "id": "evt_invoice_1",
            "type": "invoice.payment_succeeded",
            "data": {
                "object": {
                    "id": "in_1",
                    "customer": "cus_test_123",
                    "subscription": "sub_abc",
                    "amount_paid": 9500,
                    "total": 9500,
                }
            },
        }
    )
    sig = "t=0,v1=deadbeef"
    url = "/api/payments/stripe/webhook/"
    resp1 = c.post(
        url, data=payload1, content_type="application/json", HTTP_STRIPE_SIGNATURE=sig
    )
    assert resp1.status_code == 200

    bonus_tx = CommLedger.objects.filter(
        tenant=tenant, transaction_type=CommLedger.TransactionType.BONUS
    )
    assert bonus_tx.count() == 1
    assert str(bonus_tx.first().amount_eur) == "25.00"

    tenant.refresh_from_db()
    assert str(tenant.comm_credit_eur) == "25.00"

    payload2 = json.dumps(
        {
            "id": "evt_invoice_2",
            "type": "invoice.payment_succeeded",
            "data": {
                "object": {
                    "id": "in_1",
                    "customer": "cus_test_123",
                    "subscription": "sub_abc",
                    "amount_paid": 9500,
                    "total": 9500,
                }
            },
        }
    )
    resp2 = c.post(
        url, data=payload2, content_type="application/json", HTTP_STRIPE_SIGNATURE=sig
    )
    assert resp2.status_code == 200

    bonus_tx = CommLedger.objects.filter(
        tenant=tenant, transaction_type=CommLedger.TransactionType.BONUS
    )
    assert bonus_tx.count() == 1
    tenant.refresh_from_db()
    assert str(tenant.comm_credit_eur) == "25.00"
