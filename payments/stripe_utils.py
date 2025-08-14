from django.conf import settings
from .models import PaymentCustomer


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
    cust = s.Customer.create(
        email=user.email or None,
        name=(user.get_full_name() or user.username or None),
        metadata={"user_id": str(user.id)},
    )
    sc = PaymentCustomer.objects.create(user=user, stripe_customer_id=cust["id"])
    return sc.stripe_customer_id
