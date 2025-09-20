from django.urls import path
from rest_framework.routers import SimpleRouter

from ops.views import (
    OpsAlertViewSet,
    OpsAuthLoginView,
    OpsAuthRefreshView,
    OpsMetricsOverviewView,
    OpsSupportClearLockoutView,
    OpsSupportResendNotificationView,
    OpsTenantViewSet,
)

router = SimpleRouter()
router.register("tenants", OpsTenantViewSet, basename="ops-tenants")
router.register("alerts", OpsAlertViewSet, basename="ops-alerts")

urlpatterns = [
    path("auth/login/", OpsAuthLoginView.as_view(), name="ops_auth_login"),
    path("auth/refresh/", OpsAuthRefreshView.as_view(), name="ops_auth_refresh"),
    path("metrics/overview/", OpsMetricsOverviewView.as_view(), name="ops_metrics_overview"),
    path(
        "support/resend-notification/",
        OpsSupportResendNotificationView.as_view(),
        name="ops_support_resend_notification",
    ),
    path(
        "support/clear-lockout/",
        OpsSupportClearLockoutView.as_view(),
        name="ops_support_clear_lockout",
    ),
]

urlpatterns += router.urls
