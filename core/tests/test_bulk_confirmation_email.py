import datetime
import pytz
from unittest.mock import patch

import pytest

from core.email_utils import send_bulk_appointment_confirmation_email


class _FakeSMTP:
    def __init__(self, host, port):
        self.host = host
        self.port = port
        self.started_tls = False
        self.logged_in = False
        self.sent_messages = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def starttls(self):
        self.started_tls = True

    def login(self, user, password):
        self.logged_in = True

    def send_message(self, message):
        self.sent_messages.append(message)


@pytest.mark.parametrize("with_professional", [True, False])
@patch("smtplib.SMTP", new=_FakeSMTP)
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
        salon_name="Salonix",
    )

    # Obtém mensagem enviada pelo FakeSMTP (instância coletora criada abaixo)
    # A instância usada dentro da função não é esta, mas vamos verificar pelo
    # último objeto de mensagem anexado via monkeypatch global (armazenado em classe)
    # Para simplificar, recriamos e verificamos características através do conteúdo
    # do _FakeSMTP utilizado no patch: acessamos a última instância criada via patch
    # Nota: como não temos acesso direto à instância, validamos pelo comportamento do message

    # Valida estrutura multipart/alternative e conteúdo
    # O FakeSMTP armazenou a mensagem na instância interna; para conferir o conteúdo,
    # reexecutamos a função de forma controlada capturando a mensagem.

    collector = _FakeSMTP("localhost", 1025)
    with patch("smtplib.SMTP", new=lambda *args, **kwargs: collector):
        send_bulk_appointment_confirmation_email(
            to_email="alana@example.com",
            client_name="Alana Nogueira",
            items=items,
            salon_name="Salonix",
        )

    assert len(collector.sent_messages) == 1
    msg = collector.sent_messages[0]
    assert msg.is_multipart()
    assert msg.get_content_subtype() == "alternative"

    payloads = msg.get_payload()
    assert len(payloads) == 2  # plain + html
    plain = payloads[0].get_payload(decode=True).decode()
    html = payloads[1].get_payload(decode=True).decode()

    # Deve conter "Adicionar ao calendário" nas duas versões
    assert "Adicionar ao calendário" in plain
    assert "Adicionar ao calendário" in html

    # Cada item deve conter link ICS com token e rota pública
    for appt_id in (101, 102, 103):
        assert f"/api/public/appointments/{appt_id}/ics/" in html
        assert "?token=" in html
