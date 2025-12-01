from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static

from drf_spectacular.views import (
    SpectacularAPIView,
    SpectacularSwaggerView,
    SpectacularRedocView,
)

# Import admin completo
from salonix_backend.admin import admin_site
from notifications.views import PublicUnsubscribeView

urlpatterns = [
    path("", include("django_prometheus.urls")),
    path("admin/", admin_site.urls),
    path("api/", include("core.urls")),
    path("api/payments/stripe/", include("payments.urls", namespace="payments")),
    path("api/users/", include(("users.urls", "users"))),
    path("api/ops/", include("ops.urls")),
    path("api/reports/", include("reports.urls")),
    path("api/notifications/", include("notifications.urls")),
    path(
        "api/public/unsubscribe",
        PublicUnsubscribeView.as_view(),
        name="public-unsubscribe",
    ),
    # OpenAPI JSON/YAML
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    # UIs
    path(
        "api/schema/swagger/",
        SpectacularSwaggerView.as_view(url_name="schema"),
        name="swagger-ui",
    ),
    # Compat alias para documentação que referencia /api/schema/swagger-ui/
    path(
        "api/schema/swagger-ui/",
        SpectacularSwaggerView.as_view(url_name="schema"),
        name="swagger-ui-compat",
    ),
    path(
        "api/schema/redoc/",
        SpectacularRedocView.as_view(url_name="schema"),
        name="redoc",
    ),
]

# Serve media files in development
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
