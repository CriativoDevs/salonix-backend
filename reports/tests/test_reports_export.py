# reports/tests/test_reports_export.py
import pytest
from django.utils import timezone
from rest_framework.test import APIClient
from django.contrib.auth import get_user_model
from users.models import UserFeatureFlags
from django.test import override_settings

User = get_user_model()


@pytest.mark.django_db
def test_export_overview_csv_ok_without_data():
    # usuário PRO com módulo habilitado
    u = User.objects.create_user(username="csvuser", email="csv@e.com", password="x")
    UserFeatureFlags.objects.update_or_create(
        user=u, defaults={"is_pro": True, "reports_enabled": True}
    )

    c = APIClient()
    c.force_authenticate(u)

    now = timezone.now()
    start = (now - timezone.timedelta(days=7)).date().isoformat()
    end = now.date().isoformat()

    r = c.get(f"/api/reports/overview/export/?from={start}&to={end}")
    assert r.status_code == 200
    # content-type
    assert r["Content-Type"].startswith("text/csv")
    # conteúdo básico
    body = r.content.decode("utf-8")
    assert "Overview report" in body
    assert "appointments_total" in body
    assert (
        "period_start,revenue" in body.replace(" ", "").lower()
        or "period_start,revenue" in body
    )


@pytest.mark.django_db
@override_settings(
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
            "export_csv": "2/min",  # mais baixo para testar rapidamente
        },
    }
)
def test_export_overview_csv_throttled():
    u = User.objects.create_user(
        username="csvlimit", email="csvlimit@e.com", password="x"
    )
    UserFeatureFlags.objects.update_or_create(
        user=u, defaults={"is_pro": True, "reports_enabled": True}
    )

    c = APIClient()
    c.force_authenticate(u)

    now = timezone.now()
    start = (now - timezone.timedelta(days=7)).date().isoformat()
    end = now.date().isoformat()
    url = f"/api/reports/overview/export/?from={start}&to={end}"

    # duas requisições OK
    assert c.get(url).status_code == 200
    assert c.get(url).status_code == 200
    # terceira deve estourar o throttle
    r3 = c.get(url)
    assert r3.status_code in (429, 403)  # 429 esperado; 403 se algum guard falhar
