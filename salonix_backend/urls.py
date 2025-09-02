from django.contrib import admin
from django.urls import path, include

from drf_spectacular.views import (
    SpectacularAPIView,
    SpectacularSwaggerView,
    SpectacularRedocView,
)

urlpatterns = [
    path("", include("django_prometheus.urls")),
    path("admin/", admin.site.urls),
    path("api/", include("core.urls")),
    path("api/payments/stripe/", include("payments.urls", namespace="payments")),
    path("api/users/", include(("users.urls", "users"))),
    path("api/reports/", include("reports.urls")),
    path("api/notifications/", include("notifications.urls")),
    # OpenAPI JSON/YAML
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    # UIs
    path(
        "api/schema/swagger/",
        SpectacularSwaggerView.as_view(url_name="schema"),
        name="swagger-ui",
    ),
    path(
        "api/schema/redoc/",
        SpectacularRedocView.as_view(url_name="schema"),
        name="redoc",
    ),
]
