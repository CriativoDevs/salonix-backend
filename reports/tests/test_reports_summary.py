import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient
from users.models import UserFeatureFlags


User = get_user_model()


@pytest.mark.django_db
def test_reports_requires_auth():
    c = APIClient()
    r = c.get("/api/reports/summary/")
    assert r.status_code == 401


@pytest.mark.django_db
def test_reports_forbidden_without_flag():
    u = User.objects.create_user(username="u", email="u@e.com", password="x")
    UserFeatureFlags.objects.get_or_create(user=u, defaults={"reports_enabled": False})

    c = APIClient()
    c.force_authenticate(u)
    r = c.get("/api/reports/summary/")
    assert r.status_code == 403
    assert r.data["detail"] == "Módulo de relatórios desativado."


@pytest.mark.django_db
def test_reports_ok_with_flag_enabled():
    u = User.objects.create_user(username="u2", email="u2@e.com", password="x")
    ff, _ = UserFeatureFlags.objects.get_or_create(user=u)
    ff.reports_enabled = True
    ff.save(update_fields=["reports_enabled"])

    c = APIClient()
    c.force_authenticate(u)
    r = c.get("/api/reports/summary/")
    assert r.status_code == 200
    assert r.data["range"] == "last_30_days"
    assert "appointments_total" in r.data
