import pytest
from unittest.mock import patch
from django.core import signing

from core.email_utils import send_marketing_email
from notifications.views import UNSUBSCRIBE_TOKEN_SALT


class _FakeSMTP:
    def __init__(self, host, port):
        self.host = host
        self.port = port
        self.sent_messages = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def starttls(self):
        pass

    def login(self, user, password):
        pass

    def send_message(self, message):
        self.sent_messages.append(message)


@pytest.mark.django_db
@patch("smtplib.SMTP", new=_FakeSMTP)
def test_marketing_email_contains_unsubscribe_link(settings):
    settings.ICS_BASE_URL = "http://testserver"
    settings.EMAIL_HOST = "localhost"
    settings.EMAIL_PORT = 1025
    settings.EMAIL_HOST_USER = "noreply@salonix.app"
    settings.EMAIL_HOST_PASSWORD = "x"

    collector = _FakeSMTP("localhost", 1025)
    with patch("smtplib.SMTP", new=lambda *args, **kwargs: collector):
        send_marketing_email(
            to_email="cliente@example.com",
            client_name="Cliente",
            subject="Promoção",
            body_text="Descontos especiais para si.",
            tenant_id=1,
            customer_id=123,
        )

    assert len(collector.sent_messages) == 1
    msg = collector.sent_messages[0]
    assert msg.is_multipart()
    payloads = msg.get_payload()
    plain = payloads[0].get_payload(decode=True).decode()
    html = payloads[1].get_payload(decode=True).decode()

    # Deve conter rota pública e token
    assert "/api/public/unsubscribe" in plain
    assert "?token=" in plain
    assert "/api/public/unsubscribe" in html
    assert "?token=" in html

    # Extrair token simples (do plain) e validar payload
    token_part = plain.split("?token=")[-1].strip()
    payload = signing.loads(token_part, salt=UNSUBSCRIBE_TOKEN_SALT)
    assert payload["tenant_id"] == 1
    assert payload["customer_id"] == 123
    assert payload["channel"] == "email"
    assert payload["purpose"] == "marketing"
