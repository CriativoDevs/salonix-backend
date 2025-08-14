from django.conf import settings
from django.db import models
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
    cancel_at_period_end = models.BooleanField(default=False)

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
