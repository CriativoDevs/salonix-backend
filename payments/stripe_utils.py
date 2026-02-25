from django.conf import settings
from .models import PaymentCustomer
from typing import Optional, cast


PLAN_PRICE_SETTING_KEYS = {
    "basic": {
        "monthly": "STRIPE_PRICE_BASIC_MONTHLY_ID",
        "yearly": "STRIPE_PRICE_BASIC_YEARLY_ID",
    },
    "pro": {
        "monthly": "STRIPE_PRICE_PRO_MONTHLY_ID",
        "yearly": "STRIPE_PRICE_PRO_YEARLY_ID",
    },
    "founder": {
        "monthly": "STRIPE_PRICE_FOUNDER_MONTHLY_ID", # May not exist, but keeps structure
        "yearly": "STRIPE_PRICE_FOUNDER_YEARLY_ID",
    }
}

LEGACY_PLAN_SETTING_KEYS = {
    "monthly": "STRIPE_PRICE_MONTHLY_ID",
    "yearly": "STRIPE_PRICE_YEARLY_ID",
}


def _read_setting(key: str) -> Optional[str]:
    value = getattr(settings, key, "")
    return value or None


def get_plan_price_map() -> dict[str, str]:
    """
    Return mapping of plan codes to configured Stripe price ids (Defaulting to monthly).
    Kept for backward compatibility.
    """
    mapping: dict[str, str] = {}
    for plan, intervals in PLAN_PRICE_SETTING_KEYS.items():
        # Default to monthly if available
        setting_name = intervals.get("monthly")
        if setting_name:
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


def get_price_id_for_plan(plan_code: str, interval: str = "monthly") -> Optional[str]:
    plan = (plan_code or "").lower()
    interval = (interval or "monthly").lower()
    
    if interval == "annual":
        interval = "yearly"

    if plan in PLAN_PRICE_SETTING_KEYS:
        setting_key = PLAN_PRICE_SETTING_KEYS[plan].get(interval)
        if setting_key:
            return _read_setting(setting_key)

    # Fallback to legacy map if not found in structured map
    # (Only if requesting monthly, or if legacy map has yearly logic which it does somewhat)
    if interval == "monthly":
        legacy_mapping = get_legacy_price_map()
        return legacy_mapping.get(plan)
        
    return None


def get_plan_code_from_price(price_id: Optional[str]) -> Optional[str]:
    if not price_id:
        return None

    # Search in new structure (both monthly and yearly)
    for plan, intervals in PLAN_PRICE_SETTING_KEYS.items():
        for _, setting_key in intervals.items():
            val = _read_setting(setting_key)
            if val and val == price_id:
                return plan

    # Legacy fallback
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
        name=cast(
            Any,
            (
                getattr(user, "get_full_name", lambda: None)()
                or getattr(user, "username", None)
            ),
        ),
        metadata={"user_id": str(user.id)},
    )
    sc = PaymentCustomer.objects.create(user=user, stripe_customer_id=cust["id"])
    return sc.stripe_customer_id
