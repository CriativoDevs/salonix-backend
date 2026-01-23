import pytest
import stripe
from unittest.mock import MagicMock, patch
from payments.services import SubscriptionService
from users.models import CustomUser


# Mock Stripe SDK structure
class _StripeCheckoutSession:
    last_kwargs = None

    @staticmethod
    def create(**kwargs):
        _StripeCheckoutSession.last_kwargs = kwargs
        return type(
            "Obj",
            (),
            {
                "url": "https://stripe.test/checkout/sess_annual",
                "id": "sess_annual_123",
            },
        )


@pytest.mark.django_db
def test_create_checkout_session_annual_plan(monkeypatch, settings):
    # 1. Configure settings
    settings.STRIPE_API_KEY = "sk_test_xxx"
    settings.STRIPE_PRICE_BASIC_MONTHLY_ID = "price_basic_month"
    settings.STRIPE_PRICE_BASIC_YEARLY_ID = "price_basic_year"

    # 2. Mock stripe methods directly
    monkeypatch.setattr(
        stripe.checkout.Session, "create", _StripeCheckoutSession.create
    )
    # Mock Customer.create used by get_or_create_customer if it hits stripe
    # But get_or_create_customer might use PaymentCustomer.objects.get
    # Since we create a user without PaymentCustomer, it will try to create one on Stripe.
    # So we need to mock stripe.Customer.create
    monkeypatch.setattr(
        stripe.Customer,
        "create",
        lambda **kwargs: {"id": "cus_test_123"},
    )

    # 3. Create user
    user = CustomUser.objects.create_user(
        username="test_annual", email="annual@test.com", password="pass"
    )

    # 4. Call service with interval="annual"
    # Note: SubscriptionService.create_checkout_session calls get_price_id_for_plan
    # which reads from settings.

    result = SubscriptionService.create_checkout_session(
        user=user,
        plan="basic",
        success_url="http://success",
        cancel_url="http://cancel",
        interval="annual",
    )

    # 5. Verify result
    assert result["checkout_url"] == "https://stripe.test/checkout/sess_annual"

    # 6. Verify Stripe call arguments
    # It should have used the yearly price ID
    line_items = _StripeCheckoutSession.last_kwargs.get("line_items", [])
    assert len(line_items) == 1
    assert line_items[0]["price"] == "price_basic_year"

    # Verify metadata contains interval
    metadata = _StripeCheckoutSession.last_kwargs.get("subscription_data", {}).get(
        "metadata", {}
    )
    assert metadata.get("interval") == "annual"
    assert metadata.get("plan_code") == "basic"


@pytest.mark.django_db
def test_create_checkout_session_default_monthly(monkeypatch, settings):
    # Verify backward compatibility
    settings.STRIPE_API_KEY = "sk_test_xxx"
    settings.STRIPE_PRICE_BASIC_MONTHLY_ID = "price_basic_month"

    monkeypatch.setattr(
        stripe.checkout.Session, "create", _StripeCheckoutSession.create
    )
    monkeypatch.setattr(
        stripe.Customer,
        "create",
        lambda **kwargs: {"id": "cus_test_123"},
    )
    user = CustomUser.objects.create_user(
        username="test_monthly", email="monthly@test.com", password="pass"
    )

    SubscriptionService.create_checkout_session(
        user=user,
        plan="basic",
        success_url="http://success",
        cancel_url="http://cancel",
        # interval defaults to monthly
    )

    line_items = _StripeCheckoutSession.last_kwargs.get("line_items", [])
    assert line_items[0]["price"] == "price_basic_month"

    metadata = _StripeCheckoutSession.last_kwargs.get("subscription_data", {}).get(
        "metadata", {}
    )
    assert metadata.get("interval") == "monthly"
