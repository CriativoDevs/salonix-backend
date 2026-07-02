import datetime
import time
import pytz
import pytest
from django.core import mail

from core.email_utils import send_appointment_confirmation_email


@pytest.mark.django_db
def test_confirmation_email_includes_ics_calendar_link(settings):
    """
    O e-mail de confirmação de um único agendamento (fluxo mais comum de
    criação de agendamento) deve incluir um link "Adicionar ao calendário",
    tal como já acontece no e-mail de confirmação em massa. Antes desta
    correção, esta função não tinha nenhuma referência a ICS.
    """
    settings.EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
    settings.ICS_BASE_URL = "http://testserver"
    settings.EMAIL_HOST = "localhost"
    settings.EMAIL_PORT = 1025
    settings.EMAIL_HOST_USER = "noreply@salonix.app"
    settings.EMAIL_HOST_PASSWORD = "x"

    tz = pytz.timezone("Europe/Lisbon")
    start_time = tz.localize(datetime.datetime(2026, 7, 2, 15, 0))

    send_appointment_confirmation_email(
        to_email="cliente@example.com",
        client_name="Ana Cliente",
        service_name="Corte",
        date_time=start_time,
        salon_name="TimelyOne",
        appointment_id=42,
    )

    for _ in range(30):
        if len(mail.outbox) >= 1:
            break
        time.sleep(0.05)

    assert len(mail.outbox) == 1
    msg = mail.outbox[0]

    assert "Adicionar ao calendário" in msg.body
    assert "/api/public/appointments/42/ics/" in msg.body
    assert "?rid=" in msg.body

    assert len(msg.alternatives) == 1
    html_content, mimetype = msg.alternatives[0]
    assert mimetype == "text/html"
    assert "Adicionar ao calendário" in html_content
    assert "/api/public/appointments/42/ics/" in html_content


@pytest.mark.django_db
def test_confirmation_email_without_appointment_id_has_no_ics_link(settings):
    """Sem appointment_id (ou sem ICS_BASE_URL), o e-mail continua a ser
    enviado normalmente, apenas sem o link de calendário."""
    settings.EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
    settings.ICS_BASE_URL = "http://testserver"
    settings.EMAIL_HOST = "localhost"
    settings.EMAIL_PORT = 1025
    settings.EMAIL_HOST_USER = "noreply@salonix.app"
    settings.EMAIL_HOST_PASSWORD = "x"

    tz = pytz.timezone("Europe/Lisbon")
    start_time = tz.localize(datetime.datetime(2026, 7, 2, 15, 0))

    send_appointment_confirmation_email(
        to_email="cliente@example.com",
        client_name="Ana Cliente",
        service_name="Corte",
        date_time=start_time,
        salon_name="TimelyOne",
    )

    for _ in range(30):
        if len(mail.outbox) >= 1:
            break
        time.sleep(0.05)

    assert len(mail.outbox) == 1
    msg = mail.outbox[0]
    assert "Adicionar ao calendário" not in msg.body
