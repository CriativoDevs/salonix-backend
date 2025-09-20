from django.urls import path
from rest_framework.routers import SimpleRouter

from ops.views import OpsAuthLoginView, OpsAuthRefreshView, OpsTenantViewSet

router = SimpleRouter()
router.register("tenants", OpsTenantViewSet, basename="ops-tenants")

urlpatterns = [
    path("auth/login/", OpsAuthLoginView.as_view(), name="ops_auth_login"),
    path("auth/refresh/", OpsAuthRefreshView.as_view(), name="ops_auth_refresh"),
]

urlpatterns += router.urls
