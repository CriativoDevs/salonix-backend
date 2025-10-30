from django.urls import path
from reports.views import (
    ExportTopServicesCSVView,
    ExportRevenueCSVView,
    ReportsSummaryView,
    OverviewReportView,
    TopServicesReportView,
    RevenueReportView,
    ExportOverviewCSVView,
    BasicReportsView,
    AdvancedReportsView,
    ExportBasicReportsCSVView,
)
from reports.views_admin import CacheInvalidateView

app_name = "reports"

urlpatterns = [
    # Novos endpoints para relatórios básicos e avançados
    path("basic/", BasicReportsView.as_view(), name="basic_reports"),
    path("basic/export/", ExportBasicReportsCSVView.as_view(), name="basic_reports_export"),
    path("advanced/", AdvancedReportsView.as_view(), name="advanced_reports"),
    
    # Endpoints existentes
    path("summary/", ReportsSummaryView.as_view(), name="summary"),
    path("overview/", OverviewReportView.as_view(), name="overview"),
    path("top-services/", TopServicesReportView.as_view(), name="top_services"),
    path("revenue/", RevenueReportView.as_view(), name="revenue"),
    path(
        "overview/export/",
        ExportOverviewCSVView.as_view(),
        name="overview_export",
    ),
    path("top-services/export/", ExportTopServicesCSVView.as_view()),
    path("revenue/export/", ExportRevenueCSVView.as_view()),
    # Admin
    path(
        "admin/cache/invalidate/",
        CacheInvalidateView.as_view(),
        name="reports-admin-cache-invalidate",
    ),
]
