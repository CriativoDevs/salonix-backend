import pytest
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient
from django.contrib.auth import get_user_model
from django.test.utils import override_settings

User = get_user_model()


@pytest.mark.django_db
@override_settings(CAPTCHA_ENABLED=False)
def test_password_reset_request_neutral_response():
    c = APIClient()
    url = reverse("password_reset")
    r = c.post(url, {"email": "unknown@example.com", "reset_url": "http://front/reset"})
    assert r.status_code == status.HTTP_200_OK
    assert r.data.get("status") == "ok"


@pytest.mark.django_db
@override_settings(CAPTCHA_ENABLED=False)
def test_password_reset_flow_success():
    user = User.objects.create_user(username="u", email="u@example.com", password="OldPass123")
    c = APIClient()

    # request token
    req_url = reverse("password_reset")
    r1 = c.post(req_url, {"email": "u@example.com", "reset_url": "http://f/reset"})
    assert r1.status_code == 200

    # generate token directly for test
    from django.contrib.auth.tokens import PasswordResetTokenGenerator

    token = PasswordResetTokenGenerator().make_token(user)

    conf_url = reverse("password_reset_confirm")
    r2 = c.post(conf_url, {"uid": str(user.pk), "token": token, "new_password": "NewPass123"})
    assert r2.status_code == 200

    # can login with new password
    assert user.refresh_from_db() is None
    assert user.check_password("NewPass123")

