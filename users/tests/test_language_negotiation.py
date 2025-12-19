import pytest
from rest_framework.test import APIClient


@pytest.mark.django_db
def test_accept_language_header_sets_content_language(user_fixture):
    client = APIClient()
    client.force_authenticate(user=user_fixture)
    user_fixture.language_preference = "system"
    user_fixture.save(update_fields=["language_preference"])

    resp = client.get(
        "/api/users/me/profile/",
        HTTP_ACCEPT_LANGUAGE="en-US,en;q=0.9,pt;q=0.8",
    )
    assert resp.status_code == 200
    assert resp["Content-Language"] == "en"


@pytest.mark.django_db
def test_fallback_to_user_preference_when_no_header(user_fixture):
    client = APIClient()
    client.force_authenticate(user=user_fixture)
    user_fixture.language_preference = "pt-PT"
    user_fixture.save(update_fields=["language_preference"])

    resp = client.get("/api/users/me/profile/")
    assert resp.status_code == 200
    assert resp["Content-Language"] == "pt-PT"


@pytest.mark.django_db
def test_fallback_to_tenant_when_user_system_and_no_header(user_fixture):
    client = APIClient()
    client.force_authenticate(user=user_fixture)
    user_fixture.language_preference = "system"
    user_fixture.save(update_fields=["language_preference"])
    tenant = user_fixture.tenant
    tenant.preferred_language = "en"
    tenant.save(update_fields=["preferred_language"])

    resp = client.get("/api/users/me/profile/")
    assert resp.status_code == 200
    assert resp["Content-Language"] == "en"
