from django.urls import path
from .views import ReportsSummaryView

app_name = "reports"

urlpatterns = [
    path("summary/", ReportsSummaryView.as_view(), name="summary"),
]
