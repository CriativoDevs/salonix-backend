from django.contrib import admin
from .models import ExportJob, DailyReportAggregate


@admin.register(ExportJob)
class ExportJobAdmin(admin.ModelAdmin):
    list_display = ("id", "tenant", "report_type", "status", "requested_by", "created_at", "expires_at")
    list_filter = ("status", "report_type")
    search_fields = ("tenant__slug", "requested_by__email")
    readonly_fields = ("id", "created_at", "updated_at")


@admin.register(DailyReportAggregate)
class DailyReportAggregateAdmin(admin.ModelAdmin):
    list_display = ("tenant", "date", "appointments_total", "appointments_completed", "revenue_total")
    list_filter = ("tenant",)
    search_fields = ("tenant__slug",)
    readonly_fields = ("tenant", "date")
