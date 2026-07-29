from decimal import Decimal

import pytest

from payments.models import CreditPayment, PaymentCustomer
from payments.services import CreditPurchaseService
from users.models import CustomUser, Tenant, TenantStaffMember


def _setup_price_ids(monkeypatch, settings):
    settings.STRIPE_PRICE_CREDITS_5_ID = "price_credits_5_test"
    settings.STRIPE_PRICE_CREDITS_10_ID = "price_credits_10_test"
    settings.STRIPE_PRICE_CREDITS_25_ID = "price_credits_25_test"
    settings.STRIPE_PRICE_CREDITS_50_ID = "price_credits_50_test"
    settings.STRIPE_PRICE_CREDITS_100_ID = "price_credits_100_test"

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


@pytest.fixture
def owner_with_tenant(db):
    tenant = Tenant.objects.create(
        name="Auto Renewal Tenant",
        slug="auto-renewal-tenant",
        plan_tier=Tenant.PLAN_PRO,
    )
    user = CustomUser.objects.create_user(
        username="auto-renewal-owner",
        email="auto-renewal-owner@example.com",
        password="pass",
        tenant=tenant,
    )
    TenantStaffMember.objects.create(
        tenant=tenant, user=user, role=TenantStaffMember.Role.OWNER
    )
    return tenant, user


class _FakePaymentIntentSucceeded:
    id = "pi_auto_renewal_success"
    status = "succeeded"


class _FakePaymentIntentFactorySuccess:
    last_kwargs = None

    @staticmethod
    def create(**kwargs):
        _FakePaymentIntentFactorySuccess.last_kwargs = kwargs
        return _FakePaymentIntentSucceeded()


class _FakeCardError(Exception):
    pass


def _patch_stripe_success(monkeypatch, default_payment_method="pm_default_card"):
    import payments.services as payments_services

    class _StripeCustomer:
        @staticmethod
        def retrieve(customer_id):
            return {
                "id": customer_id,
                "invoice_settings": {
                    "default_payment_method": default_payment_method
                },
            }

    class _StripeErrorModule:
        CardError = _FakeCardError
        StripeError = Exception

    class _StripeSDK:
        PaymentIntent = _FakePaymentIntentFactorySuccess
        Customer = _StripeCustomer
        error = _StripeErrorModule

    monkeypatch.setattr(payments_services, "stripe", _StripeSDK, raising=True)
    return _StripeSDK


def _patch_stripe_declined(monkeypatch, default_payment_method="pm_default_card"):
    import payments.services as payments_services

    class _StripeCustomer:
        @staticmethod
        def retrieve(customer_id):
            return {
                "id": customer_id,
                "invoice_settings": {
                    "default_payment_method": default_payment_method
                },
            }

    class _FailingPaymentIntent:
        @staticmethod
        def create(**kwargs):
            raise _FakeCardError("Your card was declined.")

    class _StripeErrorModule:
        CardError = _FakeCardError
        StripeError = Exception

    class _StripeSDK:
        PaymentIntent = _FailingPaymentIntent
        Customer = _StripeCustomer
        error = _StripeErrorModule

    monkeypatch.setattr(payments_services, "stripe", _StripeSDK, raising=True)
    return _StripeSDK


@pytest.mark.django_db
def test_charge_auto_renewal_fails_without_owner(monkeypatch, settings):
    _setup_price_ids(monkeypatch, settings)
    tenant = Tenant.objects.create(
        name="No Owner Tenant", slug="no-owner-tenant", plan_tier=Tenant.PLAN_PRO
    )
    tenant.comm_auto_renew_price_id = settings.STRIPE_PRICE_CREDITS_10_ID

    result = CreditPurchaseService.charge_auto_renewal(tenant)

    assert result["success"] is False
    assert result["reason"] == "no_owner"


@pytest.mark.django_db
def test_charge_auto_renewal_fails_without_payment_customer(
    monkeypatch, settings, owner_with_tenant
):
    _setup_price_ids(monkeypatch, settings)
    tenant, _owner = owner_with_tenant
    tenant.comm_auto_renew_price_id = settings.STRIPE_PRICE_CREDITS_10_ID

    result = CreditPurchaseService.charge_auto_renewal(tenant)

    assert result["success"] is False
    assert result["reason"] == "no_payment_customer"


@pytest.mark.django_db
def test_charge_auto_renewal_fails_without_default_payment_method(
    monkeypatch, settings, owner_with_tenant
):
    _setup_price_ids(monkeypatch, settings)
    tenant, owner = owner_with_tenant
    tenant.comm_auto_renew_price_id = settings.STRIPE_PRICE_CREDITS_10_ID
    PaymentCustomer.objects.create(user=owner, stripe_customer_id="cus_no_pm")
    _patch_stripe_success(monkeypatch, default_payment_method=None)

    result = CreditPurchaseService.charge_auto_renewal(tenant)

    assert result["success"] is False
    assert result["reason"] == "no_payment_method"


@pytest.mark.django_db
def test_charge_auto_renewal_fails_with_invalid_price_id(
    monkeypatch, settings, owner_with_tenant
):
    _setup_price_ids(monkeypatch, settings)
    tenant, owner = owner_with_tenant
    tenant.comm_auto_renew_price_id = "price_unknown"
    PaymentCustomer.objects.create(user=owner, stripe_customer_id="cus_test")

    result = CreditPurchaseService.charge_auto_renewal(tenant)

    assert result["success"] is False
    assert result["reason"] == "invalid_price_id"


@pytest.mark.django_db
def test_charge_auto_renewal_success_credits_balance_and_records_payment(
    monkeypatch, settings, owner_with_tenant
):
    _setup_price_ids(monkeypatch, settings)
    tenant, owner = owner_with_tenant
    tenant.comm_auto_renew_price_id = settings.STRIPE_PRICE_CREDITS_10_ID
    tenant.comm_credit_eur = Decimal("0.00")
    tenant.save(update_fields=["comm_auto_renew_price_id", "comm_credit_eur"])
    PaymentCustomer.objects.create(user=owner, stripe_customer_id="cus_test_success")
    _patch_stripe_success(monkeypatch)

    result = CreditPurchaseService.charge_auto_renewal(tenant)

    assert result["success"] is True
    assert result["credits_purchased"] == Decimal("10.00")

    tenant.refresh_from_db()
    assert tenant.comm_credit_eur == Decimal("10.00")

    payment = CreditPayment.objects.get(
        stripe_payment_intent_id="pi_auto_renewal_success"
    )
    assert payment.status == "succeeded"
    assert payment.credits_applied is True
    assert payment.credits_purchased == Decimal("10.00")


@pytest.mark.django_db
def test_charge_auto_renewal_card_declined_returns_failure_without_raising(
    monkeypatch, settings, owner_with_tenant
):
    _setup_price_ids(monkeypatch, settings)
    tenant, owner = owner_with_tenant
    tenant.comm_auto_renew_price_id = settings.STRIPE_PRICE_CREDITS_10_ID
    tenant.comm_credit_eur = Decimal("0.00")
    tenant.save(update_fields=["comm_auto_renew_price_id", "comm_credit_eur"])
    PaymentCustomer.objects.create(user=owner, stripe_customer_id="cus_test_declined")
    _patch_stripe_declined(monkeypatch)

    result = CreditPurchaseService.charge_auto_renewal(tenant)

    assert result["success"] is False
    assert result["reason"] == "charge_failed"

    tenant.refresh_from_db()
    assert tenant.comm_credit_eur == Decimal("0.00")
