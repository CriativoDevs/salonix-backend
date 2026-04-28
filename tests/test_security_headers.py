# tests/test_security_headers.py
"""
Regression tests for BE-SEC-04 item 4: CORS/CSRF/security headers.
Validates SecurityHeadersMiddleware and settings configuration.
"""
import pytest
from django.http import HttpRequest, HttpResponse
from django.test import RequestFactory, override_settings

from salonix_backend.middleware import SecurityHeadersMiddleware


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_middleware():
    def get_response(request):
        return HttpResponse("ok")

    return SecurityHeadersMiddleware(get_response)


def _api_response(path="/api/users/me/"):
    rf = RequestFactory()
    request = rf.get(path)
    middleware = _make_middleware()
    response = HttpResponse("ok")
    return middleware.process_response(request, response)


def _non_api_response(path="/admin/"):
    rf = RequestFactory()
    request = rf.get(path)
    middleware = _make_middleware()
    response = HttpResponse("ok")
    return middleware.process_response(request, response)


# ---------------------------------------------------------------------------
# Security header presence
# ---------------------------------------------------------------------------


def test_x_content_type_options_on_api():
    resp = _api_response()
    assert resp["X-Content-Type-Options"] == "nosniff"


def test_x_frame_options_on_api():
    resp = _api_response()
    assert resp["X-Frame-Options"] == "DENY"


def test_referrer_policy_on_api():
    resp = _api_response()
    assert resp["Referrer-Policy"] == "strict-origin-when-cross-origin"


def test_permissions_policy_on_api():
    resp = _api_response()
    pp = resp["Permissions-Policy"]
    # Should restrict all sensitive browser features
    for feature in ("camera=", "geolocation=", "microphone=", "payment="):
        assert feature in pp


def test_permissions_policy_on_admin():
    resp = _non_api_response()
    assert "Permissions-Policy" in resp


# ---------------------------------------------------------------------------
# CSP path-aware
# ---------------------------------------------------------------------------


def test_api_csp_is_strict():
    resp = _api_response()
    csp = resp["Content-Security-Policy"]
    assert "default-src 'none'" in csp
    assert "frame-ancestors 'none'" in csp
    # No resources allowed for API responses
    assert "'self'" not in csp.split("default-src")[1].split(";")[0]


def test_admin_csp_allows_self():
    resp = _non_api_response()
    csp = resp["Content-Security-Policy"]
    assert "'self'" in csp
    assert "frame-ancestors 'none'" in csp
    # Admin requires inline styles; script-src should NOT have unsafe-inline
    assert "script-src 'self'" in csp
    assert "script-src 'self' 'unsafe-inline'" not in csp


def test_existing_csp_not_overwritten():
    """A view that already sets CSP should not be overridden."""
    rf = RequestFactory()
    request = rf.get("/api/test/")
    middleware = _make_middleware()
    response = HttpResponse("ok")
    response["Content-Security-Policy"] = "custom-policy"
    middleware.process_response(request, response)
    assert response["Content-Security-Policy"] == "custom-policy"


# ---------------------------------------------------------------------------
# CORS configuration
# ---------------------------------------------------------------------------


def test_cors_allow_all_origins_default_is_false():
    """CORS_ALLOW_ALL_ORIGINS must default to False (safe-by-default)."""
    from django.conf import settings

    assert not settings.CORS_ALLOW_ALL_ORIGINS


def test_cors_allowed_origins_fallback_includes_localhost():
    """Without env config, localhost origins must be allowed (dev usability)."""
    from django.conf import settings

    origins = getattr(settings, "CORS_ALLOWED_ORIGINS", [])
    assert any("localhost" in o for o in origins)


def test_cors_credentials_enabled():
    from django.conf import settings

    assert settings.CORS_ALLOW_CREDENTIALS is True


# ---------------------------------------------------------------------------
# Django security flags
# ---------------------------------------------------------------------------


def test_secure_content_type_nosniff():
    from django.conf import settings

    assert settings.SECURE_CONTENT_TYPE_NOSNIFF is True


def test_session_cookie_httponly():
    from django.conf import settings

    assert settings.SESSION_COOKIE_HTTPONLY is True


def test_csrf_cookie_httponly_is_false():
    """CSRF cookie must NOT be HttpOnly — JS needs to read it for SPA."""
    from django.conf import settings

    assert settings.CSRF_COOKIE_HTTPONLY is False
