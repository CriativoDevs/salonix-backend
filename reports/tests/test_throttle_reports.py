import pytest
from django.test.utils import override_settings
from rest_framework.test import APIClient
from django.contrib.auth import get_user_model
from users.models import UserFeatureFlags
from django.core.cache import cache

User = get_user_model()


@pytest.mark.django_db
@override_settings(
    CACHES={
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": "throttle-tests-overview",
        }
    },
    REST_FRAMEWORK={
        "DEFAULT_AUTHENTICATION_CLASSES": [
            "rest_framework_simplejwt.authentication.JWTAuthentication",
        ],
        "DEFAULT_PERMISSION_CLASSES": [
            "rest_framework.permissions.IsAuthenticated",
        ],
        "DEFAULT_THROTTLE_CLASSES": [
            "rest_framework.throttling.UserRateThrottle",
            "rest_framework.throttling.ScopedRateThrottle",
        ],
        "DEFAULT_THROTTLE_RATES": {
            "user": "1000/day",
            "reports": "2/min",
            "export_csv": "5/min",
        },
    },
)
def test_reports_overview_is_throttled():
    cache.clear()
    # usuário PRO com módulo habilitado
    user = User.objects.create_user(username="pro_thr", password="x", email="thr@e.com")
    UserFeatureFlags.objects.update_or_create(
        user=user, defaults={"is_pro": True, "reports_enabled": True}
    )
    c = APIClient()
    c.force_authenticate(user)

    # 1º e 2º devem passar
    r1 = c.get("/api/reports/overview/")
    r2 = c.get("/api/reports/overview/")
    assert r1.status_code == 200
    assert r2.status_code == 200

    # 3º deve bater no throttle (429)
    r3 = c.get("/api/reports/overview/")
    assert r3.status_code == 429


@pytest.mark.django_db
@override_settings(
    CACHES={
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": "throttle-tests-export",
        }
    },
    REST_FRAMEWORK={
        "DEFAULT_AUTHENTICATION_CLASSES": [
            "rest_framework_simplejwt.authentication.JWTAuthentication",
        ],
        "DEFAULT_PERMISSION_CLASSES": [
            "rest_framework.permissions.IsAuthenticated",
        ],
        "DEFAULT_THROTTLE_CLASSES": [
            "rest_framework.throttling.UserRateThrottle",
            "rest_framework.throttling.ScopedRateThrottle",
        ],
        "DEFAULT_THROTTLE_RATES": {
            "user": "1000/day",
            "reports": "60/min",
            "export_csv": "2/min",
        },
    },
)
def test_export_csv_is_throttled():
    cache.clear()
    user = User.objects.create_user(
        username="pro_thr_csv", password="x", email="thc@e.com"
    )
    UserFeatureFlags.objects.update_or_create(
        user=user, defaults={"is_pro": True, "reports_enabled": True}
    )
    c = APIClient()
    c.force_authenticate(user)

    # 1º e 2º devem passar
    r1 = c.get("/api/reports/overview/export/")
    r2 = c.get("/api/reports/overview/export/")
    assert r1.status_code == 200
    assert r2.status_code == 200

    # 3º deve bater no throttle (429)
    r3 = c.get("/api/reports/overview/export/")
    assert r3.status_code == 429
