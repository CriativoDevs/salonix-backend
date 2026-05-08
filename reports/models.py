import uuid
from django.db import models
from django.utils import timezone
from datetime import timedelta

from users.models import CustomUser, Tenant


def _default_expires_at():
    return timezone.now() + timedelta(hours=24)


class ExportJob(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        PROCESSING = "processing", "Processing"
        DONE = "done", "Done"
        FAILED = "failed", "Failed"

    class ReportType(models.TextChoices):
        TOP_SERVICES = "top_services", "Top Services"
        REVENUE = "revenue", "Revenue"
        BASIC = "basic", "Basic"
        ADVANCED = "advanced", "Advanced"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant = models.ForeignKey(
        Tenant,
        on_delete=models.CASCADE,
        related_name="export_jobs",
    )
    requested_by = models.ForeignKey(
        CustomUser,
        on_delete=models.SET_NULL,
        null=True,
        related_name="export_jobs",
    )
    report_type = models.CharField(max_length=32, choices=ReportType.choices)
    parameters = models.JSONField(default=dict)
    status = models.CharField(
        max_length=16, choices=Status.choices, default=Status.PENDING
    )
    file_path = models.CharField(max_length=512, blank=True)
    error_message = models.TextField(blank=True)
    expires_at = models.DateTimeField(default=_default_expires_at)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["tenant"], name="reports_exportjob_tenant_idx"),
            models.Index(
                fields=["tenant", "status"], name="rep_exportjob_tstatus_idx"
            ),
            models.Index(
                fields=["expires_at"], name="rep_exportjob_expires_idx"
            ),
        ]
        ordering = ("-created_at",)

    def __str__(self):
        return f"ExportJob {self.id} [{self.report_type}] ({self.status})"

    @property
    def is_expired(self):
        return timezone.now() >= self.expires_at
