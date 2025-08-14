import pytest
from rest_framework.test import APIClient
from django.contrib.auth import get_user_model
from users.models import UserFeatureFlags

User = get_user_model()


@pytest.mark.django_db
def test_me_features_get_and_patch():
    u = User.objects.create_user(username="u", email="u@e.com", password="x")
    ff, _ = UserFeatureFlags.objects.get_or_create(
        user=u, defaults={"sms_enabled": False}
    )

    c = APIClient()
    c.force_authenticate(u)

    r1 = c.get("/api/users/me/features/")
    assert r1.status_code == 200
    assert r1.data["sms_enabled"] is False
    assert "is_pro" in r1.data

    r2 = c.patch("/api/users/me/features/", {"sms_enabled": True}, format="json")
    assert r2.status_code == 200
    ff.refresh_from_db()
    assert ff.sms_enabled is True
