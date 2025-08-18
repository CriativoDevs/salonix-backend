import pytest
from rest_framework.test import APIClient


@pytest.mark.django_db
def test_openapi_schema_available():
    c = APIClient()
    r = c.get("/api/schema/", HTTP_ACCEPT="application/json")
    assert r.status_code == 200
    data = r.json()
    paths = data.get("paths", {})
    assert "/api/reports/summary/" in paths
    assert "/api/reports/overview/" in paths
    assert "/api/reports/top-services/" in paths
    assert "/api/reports/revenue/" in paths
    assert "/api/reports/overview/export/" in paths


@pytest.mark.django_db
def test_openapi_swagger_ui_up():
    c = APIClient()
    r = c.get("/api/schema/swagger/")
    assert r.status_code == 200


@pytest.mark.django_db
def test_openapi_redoc_ui_up():
    c = APIClient()
    r = c.get("/api/schema/redoc/")
    assert r.status_code == 200
