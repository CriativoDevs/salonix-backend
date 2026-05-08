from django.contrib import admin
from .models import ExportJob


@admin.register(ExportJob)
class ExportJobAdmin(admin.ModelAdmin):
    list_display = ("id", "tenant", "report_type", "status", "requested_by", "created_at", "expires_at")
    list_filter = ("status", "report_type")
    search_fields = ("tenant__slug", "requested_by__email")
    readonly_fields = ("id", "created_at", "updated_at")
