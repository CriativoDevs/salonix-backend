from unittest.mock import patch

import pytest
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from core.email_utils import send_staff_invite_email, send_tenant_welcome_email

IOS_URL = "https://apps.apple.com/app/id6760429848"
ANDROID_URL = "https://play.google.com/store/apps/details?id=com.timelyone.app"


def _capture_send():
    """Patcha _send_email_safe e devolve a lista de chamadas capturadas."""
    calls = []

    def fake(subject, body_plain, body_html, to_emails, reply_to=None, from_email=None):
        calls.append(
            {
                "subject": subject,
                "plain": body_plain or "",
                "html": body_html or "",
                "to": to_emails,
                "from_email": from_email,
            }
        )
        return True

    return calls, fake


@pytest.mark.django_db
def test_staff_invite_email_contains_store_links():
    calls, fake = _capture_send()
    with patch("core.email_utils._send_email_safe", side_effect=fake):
        send_staff_invite_email(
            "collab@example.com",
            "https://timelyone.today/accept?token=abc",
            salon_name="Salao X",
            inviter_name="Owner",
        )

    assert len(calls) == 1
    c = calls[0]
    # URLs presentes no HTML e no texto-plano (fallback)
    for url in (IOS_URL, ANDROID_URL):
        assert url in c["html"], f"{url} ausente do HTML do convite"
        assert url in c["plain"], f"{url} ausente do texto do convite"


@pytest.mark.django_db
def test_welcome_email_contains_store_links():
    calls, fake = _capture_send()
    with patch("core.email_utils._send_email_safe", side_effect=fake):
        send_tenant_welcome_email(
            "owner@example.com", owner_name="Owner", salon_name="Salao X"
        )

    assert len(calls) == 1
    c = calls[0]
    assert c["to"] == "owner@example.com" or c["to"] == ["owner@example.com"]
    for url in (IOS_URL, ANDROID_URL):
        assert url in c["html"], f"{url} ausente do HTML do welcome"
        assert url in c["plain"], f"{url} ausente do texto do welcome"


@pytest.mark.django_db
def test_registration_triggers_welcome_email():
    with patch("users.views.send_tenant_welcome_email", return_value=True) as mock_welcome:
        client = APIClient()
        url = reverse("users:register")
        payload = {
            "username": "welcomeuser",
            "email": "welcome@example.com",
            "password": "Password123!",
            "salon_name": "Welcome Salon",
            "plan": "founder",
        }
        resp = client.post(url, payload)

    assert resp.status_code == status.HTTP_201_CREATED
    assert mock_welcome.called
    # email do owner foi passado ao welcome
    sent_to = mock_welcome.call_args.args[0] if mock_welcome.call_args.args else (
        mock_welcome.call_args.kwargs.get("to_email")
    )
    assert sent_to == "welcome@example.com"


@pytest.mark.django_db
def test_welcome_email_failure_does_not_break_registration():
    with patch(
        "users.views.send_tenant_welcome_email",
        side_effect=RuntimeError("smtp down"),
    ):
        client = APIClient()
        url = reverse("users:register")
        payload = {
            "username": "resilientuser",
            "email": "resilient@example.com",
            "password": "Password123!",
            "salon_name": "Resilient Salon",
            "plan": "founder",
        }
        resp = client.post(url, payload)

    assert resp.status_code == status.HTTP_201_CREATED
