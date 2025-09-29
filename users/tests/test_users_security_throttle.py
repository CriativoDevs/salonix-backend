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
            "LOCATION": "users-throttle-login",
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
            "auth_login": "2/min",
            "auth_register": "5/min",
            "tenant_meta_public": "100/min",
        },
    },
    CAPTCHA_ENABLED=False,
)
def test_login_is_throttled():
    client = APIClient()
    token_url = reverse("token_obtain_pair")

    User.objects.create_user(username="u1", email="u1@example.com", password="p@ss12345")
    payload = {"email": "u1@example.com", "password": "p@ss12345"}

    r1 = client.post(token_url, data=payload)
    r2 = client.post(token_url, data=payload)
    assert r1.status_code == 200
    assert r2.status_code == 200
    r3 = client.post(token_url, data=payload)
    assert r3.status_code == status.HTTP_429_TOO_MANY_REQUESTS


@pytest.mark.django_db
@override_settings(
    CACHES={
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": "users-throttle-register",
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
            "auth_login": "100/min",
            "auth_register": "2/min",
            "tenant_meta_public": "100/min",
        },
    },
    CAPTCHA_ENABLED=False,
)
def test_register_is_throttled():
    client = APIClient()
    url = reverse("register")
    p = {"username": "x", "email": "x1@example.com", "password": "StrongPass123"}
    r1 = client.post(url, data=p)
    assert r1.status_code == status.HTTP_201_CREATED
    p2 = {"username": "y", "email": "x2@example.com", "password": "StrongPass123"}
    r2 = client.post(url, data=p2)
    assert r2.status_code == status.HTTP_201_CREATED
    p3 = {"username": "z", "email": "x3@example.com", "password": "StrongPass123"}
    r3 = client.post(url, data=p3)
    assert r3.status_code == status.HTTP_429_TOO_MANY_REQUESTS


@pytest.mark.django_db
@override_settings(CAPTCHA_ENABLED=True, CAPTCHA_BYPASS_TOKEN="dev-bypass")
def test_login_with_captcha_bypass_succeeds():
    client = APIClient()
    token_url = reverse("token_obtain_pair")
    User.objects.create_user(username="u1", email="u1@example.com", password="p@ss12345")
    payload = {"email": "u1@example.com", "password": "p@ss12345"}
    # enviar header de bypass
    r = client.post(token_url, data=payload, HTTP_X_CAPTCHA_TOKEN="dev-bypass")
    assert r.status_code == status.HTTP_200_OK


@pytest.mark.django_db
@override_settings(CAPTCHA_ENABLED=True, CAPTCHA_BYPASS_TOKEN="")
def test_login_with_invalid_captcha_fails():
    client = APIClient()
    token_url = reverse("token_obtain_pair")
    User.objects.create_user(username="u2", email="u2@example.com", password="p@ss12345")
    payload = {"email": "u2@example.com", "password": "p@ss12345", "captcha_token": "invalid"}
    r = client.post(token_url, data=payload)
    assert r.status_code == status.HTTP_400_BAD_REQUEST

