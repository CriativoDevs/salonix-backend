from django.conf import settings
from django.db import models
from typing import Any, cast
from django.utils import timezone

User = settings.AUTH_USER_MODEL


class PaymentCustomer(models.Model):
    user = models.OneToOneField(
        User, on_delete=models.CASCADE, related_name="payment_customer"
    )
    stripe_customer_id = models.CharField(max_length=255, unique=True)

    def __str__(self):
        return f"{self.user} - {self.stripe_customer_id}"


class Subscription(models.Model):
    STATUS_CHOICES = (
        ("incomplete", "incomplete"),
        ("trialing", "trialing"),
        ("active", "active"),
        ("past_due", "past_due"),
        ("canceled", "canceled"),
        ("unpaid", "unpaid"),
    )
    user = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="subscriptions"
    )
    stripe_subscription_id = models.CharField(max_length=255, unique=True)
    status = models.CharField(max_length=32, choices=STATUS_CHOICES)
    price_id = models.CharField(max_length=255, blank=True, null=True)
    current_period_end = models.DateTimeField(blank=True, null=True)
    cancel_at_period_end = models.BooleanField(default=cast(Any, False))

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["user", "status"]),
        ]

    def __str__(self):
        return f"{self.user} - {self.status} - {self.stripe_subscription_id}"

    @property
    def is_active(self) -> bool:
        return self.status in {"trialing", "active"} and (
            not self.cancel_at_period_end
            or (self.current_period_end and self.current_period_end > timezone.now())
        )


class CreditPayment(models.Model):
    """Modelo para pagamentos de créditos via Stripe"""

    STATUS_CHOICES = (
        ("pending", "Pending"),
        ("processing", "Processing"),
        ("succeeded", "Succeeded"),
        ("failed", "Failed"),
        ("canceled", "Canceled"),
    )

    CREDIT_AMOUNTS = (
        (5.00, "5 EUR"),
        (10.00, "10 EUR"),
        (25.00, "25 EUR"),
        (50.00, "50 EUR"),
        (100.00, "100 EUR"),
    )

    user = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="credit_payments"
    )
    tenant = models.ForeignKey(
        "users.Tenant", on_delete=models.CASCADE, related_name="credit_payments"
    )

    # Stripe fields
    stripe_payment_intent_id = models.CharField(max_length=255, unique=True)
    stripe_customer_id = models.CharField(max_length=255)
    stripe_price_id = models.CharField(max_length=255)

    # Payment details
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    currency = models.CharField(max_length=3, default="EUR")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="pending")

    # Credit details
    credits_purchased = models.DecimalField(max_digits=10, decimal_places=2)
    credits_applied = models.BooleanField(default=False)

    # Metadata
    metadata = models.JSONField(default=dict, blank=True)

    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["user", "status"]),
            models.Index(fields=["tenant", "status"]),
            models.Index(fields=["stripe_payment_intent_id"]),
            models.Index(fields=["created_at"]),
        ]
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.user} - {self.amount} {self.currency} - {self.status}"

    @property
    def is_completed(self) -> bool:
        return self.status == "succeeded"

    @property
    def can_apply_credits(self) -> bool:
        return self.is_completed and not self.credits_applied


class StripeWebhookEvent(models.Model):
    """Modelo para rastrear eventos de webhook do Stripe"""

    stripe_event_id = models.CharField(max_length=255, unique=True)
    event_type = models.CharField(max_length=100)
    processed = models.BooleanField(default=False)
    processing_error = models.TextField(blank=True, null=True)

    # Dados do evento
    event_data = models.JSONField()

    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    processed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["stripe_event_id"]),
            models.Index(fields=["event_type", "processed"]),
            models.Index(fields=["created_at"]),
        ]
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.event_type} - {self.stripe_event_id} - {'Processed' if self.processed else 'Pending'}"
