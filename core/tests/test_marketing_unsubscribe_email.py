import pytest
from django.core import signing
from django.core import mail
from django.test.utils import override_settings

from core.email_utils import send_marketing_email
from notifications.views import UNSUBSCRIBE_TOKEN_SALT


@pytest.mark.django_db
@override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
def test_marketing_email_contains_unsubscribe_link(settings):
    settings.ICS_BASE_URL = "http://testserver"
    settings.EMAIL_HOST = "localhost"
    settings.EMAIL_PORT = 1025
    settings.EMAIL_HOST_USER = "noreply@salonix.app"
    settings.EMAIL_HOST_PASSWORD = "x"

    send_marketing_email(
        to_email="cliente@example.com",
        client_name="Cliente",
        subject="Promoção",
        body_text="Descontos especiais para si.",
        tenant_id=1,
        customer_id=123,
    )

    assert len(mail.outbox) == 1
    msg = mail.outbox[0]
    
    # Verifica multipart
    assert isinstance(msg, mail.EmailMultiAlternatives)
    
    # Verifica conteúdo
    plain = msg.body
    # HTML está nas alternatives
    assert len(msg.alternatives) == 1
    html = msg.alternatives[0][0]

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
