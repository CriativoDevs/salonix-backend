from django.urls import path
from . import views

app_name = "reports"

urlpatterns = [
    path("summary/", views.ReportsSummaryView.as_view(), name="summary"),
    path("overview/", views.OverviewReportView.as_view(), name="overview"),
    path("top-services/", views.TopServicesReportView.as_view(), name="top_services"),
    path("revenue/", views.RevenueReportView.as_view(), name="revenue"),
    path(
        "overview/export/",
        views.ExportOverviewCSVView.as_view(),
        name="overview_export",
    ),
]
