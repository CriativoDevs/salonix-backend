import pytest
from django.test.utils import override_settings
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient
from django.contrib.auth import get_user_model

User = get_user_model()


@pytest.mark.django_db
@override_settings(
    CACHES={
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": "core-throttle-compliance",
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
            "auth_login": "1/min",
        },
        # Ensure our custom handler is active
        "EXCEPTION_HANDLER": "salonix_backend.error_handling.custom_exception_handler",
        "DEFAULT_RENDERER_CLASSES": [
            "rest_framework.renderers.JSONRenderer",
        ],
    },
    CAPTCHA_ENABLED=False,
)
def test_throttling_response_format():
    """
    Verifica se a resposta 429 segue o padrão:
    1. Header Retry-After presente (segundos)
    2. Body JSON com estrutura padronizada e campo 'wait'
    """
    client = APIClient()
    token_url = reverse("token_obtain_pair")

    User.objects.create_user(
        username="u_throttle", email="u_throttle@example.com", password="p@ss12345"
    )
    payload = {"email": "u_throttle@example.com", "password": "p@ss12345"}

    # 1st request: OK
    r1 = client.post(token_url, data=payload)
    assert r1.status_code == 200

    # 2nd request: Throttled (limit is 1/min)
    r2 = client.post(token_url, data=payload)
    assert r2.status_code == status.HTTP_429_TOO_MANY_REQUESTS

    # Check Header
    assert "Retry-After" in r2.headers
    retry_after = r2.headers["Retry-After"]
    assert retry_after.isdigit()
    print(f"\n[DEBUG] Retry-After Header: {retry_after}")

    # Check Body
    data = r2.json()
    print(f"\n[DEBUG] 429 Response Body: {data}")

    assert "error" in data
    error = data["error"]
    assert error["code"] == "E304"  # SYSTEM_RATE_LIMIT_EXCEEDED

    # Requirement: Padronizar corpo da resposta JSON (ex: `wait` explícito)
    # Check if 'wait' is in details
    assert "details" in error
    # This is what we expect to fail if not implemented yet
    if "wait" not in error["details"]:
        pytest.fail(f"'wait' field missing in error details: {error['details']}")

    assert error["details"]["wait"] > 0
    assert error["details"]["retry_after"] == error["details"]["wait"]


@pytest.mark.django_db
@override_settings(
    CACHES={
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": "core-throttle-compliance-anon-real",
        }
    },
    REST_FRAMEWORK={
        "DEFAULT_AUTHENTICATION_CLASSES": [
            "rest_framework_simplejwt.authentication.JWTAuthentication",
        ],
        "DEFAULT_PERMISSION_CLASSES": [
            "rest_framework.permissions.AllowAny",
        ],
        "EXCEPTION_HANDLER": "salonix_backend.error_handling.custom_exception_handler",
        "DEFAULT_RENDERER_CLASSES": [
            "rest_framework.renderers.JSONRenderer",
        ],
        "DEFAULT_THROTTLE_RATES": {
            "auth_login": "1/min",
        },
    },
)
def test_throttling_anon_response_format():
    """
    Verifica se a resposta 429 para anônimos também segue o padrão,
    usando a view real de login (que sobrescreve throttle classes).
    """
    client = APIClient()
    url = reverse("token_obtain_pair")

    # 1st request: OK (Fail auth but not throttled yet)
    r1 = client.post(url, {})
    assert r1.status_code != 429

    # 2nd request: Throttled
    r2 = client.post(url, {})
    assert r2.status_code == status.HTTP_429_TOO_MANY_REQUESTS

    # Check Header
    assert "Retry-After" in r2.headers

    # Check Body
    data = r2.json()
    error = data["error"]
    assert error["code"] == "E304"
    assert "wait" in error["details"]
    assert error["details"]["wait"] > 0
