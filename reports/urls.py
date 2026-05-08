from django.urls import path
from reports.views_export import ExportJobCreateView, ExportJobStatusView, ExportJobDownloadView
from reports.views import (
    ExportTopServicesCSVView,
    ExportRevenueCSVView,
    ReportsSummaryView,
    OverviewReportView,
    TopServicesReportView,
    RevenueSeriesReportView,
    RetentionReportView,
    ExportOverviewCSVView,
    BasicReportsView,
    AdvancedReportsView,
    ExportBasicReportsCSVView,
    ExportAdvancedReportsCSVView,
)
from reports.views_admin import CacheInvalidateView

app_name = "reports"

urlpatterns = [
    # Novos endpoints para relatórios básicos e avançados
    path("basic/", BasicReportsView.as_view(), name="basic_reports"),
    path(
        "basic/export/",
        ExportBasicReportsCSVView.as_view(),
        name="basic_reports_export",
    ),
    path("advanced/", AdvancedReportsView.as_view(), name="advanced_reports"),
    path(
        "advanced/export/",
        ExportAdvancedReportsCSVView.as_view(),
        name="advanced_reports_export",
    ),
    # Endpoints existentes
    path("summary/", ReportsSummaryView.as_view(), name="summary"),
    path("overview/", OverviewReportView.as_view(), name="overview"),
    path("top-services/", TopServicesReportView.as_view(), name="top_services"),
    path("revenue/", RevenueSeriesReportView.as_view(), name="revenue"),
    path("retention/", RetentionReportView.as_view(), name="retention"),
    path(
        "overview/export/",
        ExportOverviewCSVView.as_view(),
        name="overview_export",
    ),
    path("top-services/export/", ExportTopServicesCSVView.as_view()),
    path("revenue/export/", ExportRevenueCSVView.as_view()),
    # Async export
    path("exports/", ExportJobCreateView.as_view(), name="export_job_create"),
    path("exports/<uuid:job_id>/", ExportJobStatusView.as_view(), name="export_job_status"),
    path("exports/<uuid:job_id>/download/", ExportJobDownloadView.as_view(), name="export_job_download"),

    # Admin
    path(
        "admin/cache/invalidate/",
        CacheInvalidateView.as_view(),
        name="reports-admin-cache-invalidate",
    ),
]
