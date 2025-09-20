from __future__ import annotations

from django.conf import settings
from django.db import models
from django.utils import timezone
from typing import Any, Dict


class OpsAlert(models.Model):
    class Categories(models.TextChoices):
        NOTIFICATION_FAILURE = "notification_failure", "Notification Failure"
        SECURITY_INCIDENT = "security_incident", "Security Incident"
        SYSTEM = "system", "System"

    class Severity(models.TextChoices):
        INFO = "info", "Info"
        WARNING = "warning", "Warning"
        CRITICAL = "critical", "Critical"

    id = models.BigAutoField(primary_key=True)
    category = models.CharField(max_length=40, choices=Categories.choices)
    severity = models.CharField(max_length=20, choices=Severity.choices)
    message = models.CharField(max_length=255)
    metadata = models.JSONField(default=dict, blank=True)
    tenant = models.ForeignKey(
        "users.Tenant",
        on_delete=models.SET_NULL,
        related_name="ops_alerts",
        null=True,
        blank=True,
    )
    notification_log = models.ForeignKey(
        "notifications.NotificationLog",
        on_delete=models.SET_NULL,
        related_name="ops_alerts",
        null=True,
        blank=True,
    )
    resolved_at = models.DateTimeField(null=True, blank=True)
    resolved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="ops_alerts_resolved",
        null=True,
        blank=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["category", "severity"]),
            models.Index(fields=["resolved_at"]),
            models.Index(fields=["created_at"]),
        ]
        ordering = ["-created_at"]

    def mark_resolved(self, user=None) -> None:
        if self.resolved_at:
            return
        self.resolved_at = timezone.now()
        if user:
            self.resolved_by = user
        self.save(update_fields=["resolved_at", "resolved_by", "updated_at"])

    @property
    def is_resolved(self) -> bool:
        return bool(self.resolved_at)


class AccountLockout(models.Model):
    id = models.BigAutoField(primary_key=True)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="account_lockouts",
    )
    tenant = models.ForeignKey(
        "users.Tenant",
        on_delete=models.CASCADE,
        related_name="account_lockouts",
    )
    reason = models.CharField(max_length=255)
    source = models.CharField(max_length=100, default="auth")
    locked_at = models.DateTimeField(default=timezone.now)
    metadata = models.JSONField(default=dict, blank=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    resolved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="account_lockouts_resolved",
        null=True,
        blank=True,
    )

    class Meta:
        indexes = [
            models.Index(fields=["tenant", "locked_at"]),
            models.Index(fields=["resolved_at"]),
        ]
        ordering = ["-locked_at"]

    def resolve(self, user=None) -> None:
        if self.resolved_at:
            return
        self.resolved_at = timezone.now()
        if user:
            self.resolved_by = user
        self.save(update_fields=["resolved_at", "resolved_by"])

    @property
    def is_active(self) -> bool:
        return self.resolved_at is None


class OpsSupportAuditLog(models.Model):
    class Actions(models.TextChoices):
        RESEND_NOTIFICATION = "resend_notification", "Resend Notification"
        CLEAR_LOCKOUT = "clear_lockout", "Clear Lockout"
        RESOLVE_ALERT = "resolve_alert", "Resolve Alert"

    id = models.BigAutoField(primary_key=True)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="ops_support_actions",
        null=True,
        blank=True,
    )
    action = models.CharField(max_length=40, choices=Actions.choices)
    target_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="ops_support_targets",
        null=True,
        blank=True,
    )
    target_tenant = models.ForeignKey(
        "users.Tenant",
        on_delete=models.SET_NULL,
        related_name="ops_support_actions",
        null=True,
        blank=True,
    )
    payload = models.JSONField(default=dict, blank=True)
    result = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["action", "created_at"]),
            models.Index(fields=["actor", "created_at"]),
        ]
        ordering = ["-created_at"]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "action": self.action,
            "actor_id": self.actor_id,
            "target_user_id": self.target_user_id,
            "target_tenant_id": self.target_tenant_id,
            "payload": self.payload,
            "result": self.result,
            "created_at": self.created_at.isoformat(),
        }

