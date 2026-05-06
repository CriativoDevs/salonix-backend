import datetime
import time
import pytz
import pytest
from django.core import mail
from django.test.utils import override_settings

from core.email_utils import send_bulk_appointment_confirmation_email


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
@pytest.mark.parametrize("with_professional", [True, False])
def test_send_bulk_email_multipart_and_links(settings, with_professional):
    # Configura base para links ICS
    settings.ICS_BASE_URL = "http://testserver"
    settings.EMAIL_HOST = "localhost"
    settings.EMAIL_PORT = 1025
    settings.EMAIL_HOST_USER = "noreply@salonix.app"
    settings.EMAIL_HOST_PASSWORD = "x"

    tz = pytz.timezone("Europe/Lisbon")
    dt1 = tz.localize(datetime.datetime(2025, 12, 11, 16, 0))
    dt2 = tz.localize(datetime.datetime(2025, 12, 19, 17, 30))
    dt3 = tz.localize(datetime.datetime(2025, 12, 17, 13, 0))

    items = [
        {
            "service_name": "Sobrancelha",
            "start_time": dt1,
            "professional_name": "Luiz",
            "appointment_id": 101,
        },
        {
            "service_name": "Sobrancelha",
            "start_time": dt2,
            "professional_name": ("Luiz" if with_professional else None),
            "appointment_id": 102,
        },
        {
            "service_name": "Sobrancelha",
            "start_time": dt3,
            "professional_name": "Luiz",
            "appointment_id": 103,
        },
    ]

    # Executa envio
    send_bulk_appointment_confirmation_email(
        to_email="alana@example.com",
        client_name="Alana Nogueira",
        items=items,
        salon_name="TimelyOne",
    )

    # O envio é assíncrono (thread); aguarda brevemente para evitar flaky test.
    for _ in range(30):
        if len(mail.outbox) >= 1:
            break
        time.sleep(0.05)

    # Verificações usando django.core.mail.outbox
    assert len(mail.outbox) == 1
    msg = mail.outbox[0]

    # Verifica assunto e destinatário
    assert msg.subject == "Confirmação dos seus agendamentos"
    assert msg.to == ["alana@example.com"]

    # Verifica corpo em texto plano
    plain = msg.body
    assert "Adicionar ao calendário" in plain

    # Verifica corpo HTML (alternativa)
    assert len(msg.alternatives) == 1
    html_content, mimetype = msg.alternatives[0]
    assert mimetype == "text/html"
    assert "Adicionar ao calendário" in html_content

    # Cada item deve conter link ICS com token e rota pública
    for appt_id in (101, 102, 103):
        expected_link_part = f"/api/public/appointments/{appt_id}/ics/"
        assert expected_link_part in html_content
        assert "?rid=" in html_content
    assert "?token=" not in html_content
