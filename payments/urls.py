# payments/urls.py
from django.urls import path
from .views import (
    CreateCheckoutSession,
    CreatePortalSession,
    StripeWebhookView,
)

app_name = "payments"

urlpatterns = [
    path(
        "create-checkout-session/",
        CreateCheckoutSession.as_view(),
        name="create_checkout_session",
    ),
    path(
        "billing-portal/",
        CreatePortalSession.as_view(),  # << era ManageBillingPortal
        name="billing_portal",
    ),
    path(
        "webhook/",
        StripeWebhookView.as_view(),  # << era StripeWebhook
        name="stripe_webhook",
    ),
]
