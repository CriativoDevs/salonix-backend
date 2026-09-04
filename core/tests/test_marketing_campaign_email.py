"""
BE-MARKETING-04 (#522): reply_to editável pelo tenant e From sempre no
nosso domínio verificado (nunca o email do tenant), mesmo com reply_to
setado.
"""

from unittest.mock import patch

import pytest

from core import email_utils


def _capture_send_email_safe():
    calls = []

    def fake(subject, body_plain, body_html, to_emails, reply_to=None, from_email=None):
        calls.append(
            {
                "subject": subject,
                "to": to_emails,
                "from_email": from_email,
                "reply_to": reply_to,
            }
        )
        return True

    return calls, fake


@pytest.mark.django_db
class TestMarketingEmailReplyToAndFrom:
    def test_from_is_our_domain_with_tenant_display_name(self):
        calls, fake = _capture_send_email_safe()
        with patch("core.email_utils._send_email_safe", side_effect=fake):
            email_utils.send_marketing_email(
                "cliente@example.com",
                "Cliente",
                "Assunto",
                "corpo",
                tenant_id=1,
                customer_id=1,
                salon_name="Salão da Maria",
            )
        # Nome de exibição com acento é MIME-encoded pelo email.utils.formataddr
        # (comportamento correto/esperado para headers RFC 2047).
        from email.utils import formataddr

        assert calls[0]["from_email"] == formataddr(
            ("Salão da Maria via TimelyOne", "support@timelyone.today")
        )
        assert calls[0]["from_email"].endswith("<support@timelyone.today>")

    def test_default_salon_name_keeps_plain_support_sender(self):
        calls, fake = _capture_send_email_safe()
        with patch("core.email_utils._send_email_safe", side_effect=fake):
            email_utils.send_marketing_email(
                "cliente@example.com",
                "Cliente",
                "Assunto",
                "corpo",
                tenant_id=1,
                customer_id=1,
            )
        assert calls[0]["from_email"] == "TimelyOne <support@timelyone.today>"

    def test_reply_to_applied_when_informed(self):
        calls, fake = _capture_send_email_safe()
        with patch("core.email_utils._send_email_safe", side_effect=fake):
            email_utils.send_marketing_email(
                "cliente@example.com",
                "Cliente",
                "Assunto",
                "corpo",
                tenant_id=1,
                customer_id=1,
                salon_name="Salão da Maria",
                reply_to="tenant-owner@example.com",
            )
        assert calls[0]["reply_to"] == ["tenant-owner@example.com"]
        # From nunca é o email do tenant, mesmo com reply_to setado.
        assert "tenant-owner@example.com" not in calls[0]["from_email"]
        assert "timelyone.today" in calls[0]["from_email"]

    def test_reply_to_omitted_when_not_informed(self):
        calls, fake = _capture_send_email_safe()
        with patch("core.email_utils._send_email_safe", side_effect=fake):
            email_utils.send_marketing_email(
                "cliente@example.com",
                "Cliente",
                "Assunto",
                "corpo",
                tenant_id=1,
                customer_id=1,
                salon_name="Salão da Maria",
            )
        assert calls[0]["reply_to"] is None
