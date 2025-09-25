from django.conf import settings
from .models import PaymentCustomer
from typing import Optional, cast


PLAN_PRICE_SETTING_KEYS = {
    "basic": "STRIPE_PRICE_BASIC_MONTHLY_ID",
    "standard": "STRIPE_PRICE_STANDARD_MONTHLY_ID",
    "pro": "STRIPE_PRICE_PRO_MONTHLY_ID",
    "enterprise": "STRIPE_PRICE_ENTERPRISE_MONTHLY_ID",
}

LEGACY_PLAN_SETTING_KEYS = {
    "monthly": "STRIPE_PRICE_MONTHLY_ID",
    "yearly": "STRIPE_PRICE_YEARLY_ID",
}


def _read_setting(key: str) -> Optional[str]:
    value = getattr(settings, key, "")
    return value or None


def get_plan_price_map() -> dict[str, str]:
    """Return mapping of plan codes to configured Stripe price ids."""

    mapping: dict[str, str] = {}
    for plan, setting_name in PLAN_PRICE_SETTING_KEYS.items():
        value = _read_setting(setting_name)
        if value:
            mapping[plan] = value
    return mapping


def get_legacy_price_map() -> dict[str, str]:
    mapping: dict[str, str] = {}
    for plan, setting_name in LEGACY_PLAN_SETTING_KEYS.items():
        value = _read_setting(setting_name)
        if value:
            mapping[plan] = value
    return mapping


def get_price_id_for_plan(plan_code: str) -> Optional[str]:
    plan = (plan_code or "").lower()
    mapping = get_plan_price_map()
    if plan in mapping:
        return mapping[plan]

    legacy_mapping = get_legacy_price_map()
    return legacy_mapping.get(plan)


def get_plan_code_from_price(price_id: Optional[str]) -> Optional[str]:
    if not price_id:
        return None

    mapping = get_plan_price_map()
    inverse = {value: key for key, value in mapping.items()}
    if price_id in inverse:
        return inverse[price_id]

    legacy_mapping = get_legacy_price_map()
    inverse_legacy = {value: key for key, value in legacy_mapping.items()}
    return inverse_legacy.get(price_id)


def get_stripe():
    import stripe

    api_key = getattr(settings, "STRIPE_API_KEY", None)
    api_version = getattr(settings, "STRIPE_API_VERSION", None)
    if api_key:
        stripe.api_key = api_key
    if api_version:
        stripe.api_version = api_version
    return stripe


def get_or_create_customer(user):
    """
    Garante que o usuário tenha um stripe_customer_id persistido em PaymentCustomer.
    """
    sc = getattr(user, "payment_customer", None)
    s = get_stripe()
    if sc and sc.stripe_customer_id:
        return sc.stripe_customer_id

    # cria Customer no Stripe
    from typing import Any
    cust = s.Customer.create(
        email=cast(Any, getattr(user, "email", None)),
        name=cast(Any, (getattr(user, "get_full_name", lambda: None)() or getattr(user, "username", None))),
        metadata={"user_id": str(user.id)},
    )
    sc = PaymentCustomer.objects.create(user=user, stripe_customer_id=cust["id"])
    return sc.stripe_customer_id
