# payments/urls.py
from django.urls import path
from .views import (
    CreateCheckoutSession,
    CreatePortalSession,
    AvailableCreditPackagesView,
    CreateCreditPaymentIntentView,
    # Novas views para sistema completo de assinaturas
    AvailablePlansView,
    CurrentSubscriptionView,
    SubscriptionActionView,
    PaymentHistoryView,
    BillingOverviewView,
    ImprovedCheckoutSessionView,
    ImprovedPortalSessionView,
    StripeSettingsView,
)
from .webhooks import StripeWebhookView

app_name = "payments"

urlpatterns = [
    # URLs originais (mantidas para compatibilidade)
    path(
        "create-checkout-session/",
        CreateCheckoutSession.as_view(),
        name="create_checkout_session",
    ),
    path(
        "billing-portal/",
        CreatePortalSession.as_view(),
        name="billing_portal",
    ),
    path(
        "webhook/",
        StripeWebhookView.as_view(),
        name="stripe_webhook",
    ),
    path(
        "credits/packages/",
        AvailableCreditPackagesView.as_view(),
        name="available_credit_packages",
    ),
    path(
        "credits/purchase/",
        CreateCreditPaymentIntentView.as_view(),
        name="create_credit_payment_intent",
    ),
    # Novas URLs para sistema completo de assinaturas
    path(
        "plans/",
        AvailablePlansView.as_view(),
        name="available_plans",
    ),
    path(
        "subscription/current/",
        CurrentSubscriptionView.as_view(),
        name="current_subscription",
    ),
    path(
        "subscription/action/",
        SubscriptionActionView.as_view(),
        name="subscription_action",
    ),
    path(
        "history/",
        PaymentHistoryView.as_view(),
        name="payment_history",
    ),
    path(
        "overview/",
        BillingOverviewView.as_view(),
        name="billing_overview",
    ),
    path(
        "settings/",
        StripeSettingsView.as_view(),
        name="stripe_settings",
    ),
    # URLs melhoradas (v2)
    path(
        "v2/checkout/",
        ImprovedCheckoutSessionView.as_view(),
        name="improved_checkout_session",
    ),
    path(
        "v2/portal/",
        ImprovedPortalSessionView.as_view(),
        name="improved_portal_session",
    ),
]
