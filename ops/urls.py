from django.urls import path
from rest_framework.routers import SimpleRouter

from ops.views import (
    OpsAlertViewSet,
    OpsAuthLoginView,
    OpsAuthMeView,
    OpsAuthRefreshView,
    OpsMetricsOverviewView,
    OpsTenantViewSet,
    OpsUserViewSet,
    OpsSupportViewSet,
)

router = SimpleRouter()
router.register("tenants", OpsTenantViewSet, basename="ops-tenants")
router.register("alerts", OpsAlertViewSet, basename="ops-alerts")
router.register("users", OpsUserViewSet, basename="ops-users")
router.register("support", OpsSupportViewSet, basename="ops-support")

urlpatterns = [
    path("auth/login/", OpsAuthLoginView.as_view(), name="ops_auth_login"),
    path("auth/refresh/", OpsAuthRefreshView.as_view(), name="ops_auth_refresh"),
    path("auth/me/", OpsAuthMeView.as_view(), name="ops_auth_me"),
    path(
        "metrics/overview/",
        OpsMetricsOverviewView.as_view(),
        name="ops_metrics_overview",
    ),
]

urlpatterns += router.urls
