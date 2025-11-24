import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from django.conf import settings
from django.core import signing
from notifications.views import UNSUBSCRIBE_TOKEN_SALT
from core.utils.ics import compute_public_ics_token


def send_appointment_confirmation_email(
    to_email, client_name, service_name, date_time, salon_name="Salonix"
):
    """
    Envia e-mail de confirmação de agendamento via SMTP (Gmail).

    Args:
        to_email (str): Email do cliente
        client_name (str): Nome do cliente
        service_name (str): Nome do serviço agendado
        date_time (datetime): Data e hora do agendamento
    """
    subject = "Confirmação do seu agendamento"
    sender_email = settings.EMAIL_HOST_USER
    receiver_email = to_email

    formatted_date = date_time.strftime("%d/%m/%Y às %H:%M")

    body = f"""
    Olá {client_name},

    Seu agendamento para o serviço "{service_name}" foi confirmado com sucesso!

    📅 Data e hora: {formatted_date}

    Caso precise remarcar ou cancelar, entre em contato conosco com antecedência.

    Obrigado por escolher {salon_name}! 💈
    """

    # Cria a mensagem
    message = MIMEMultipart()
    message["From"] = sender_email
    message["To"] = receiver_email
    message["Subject"] = subject

    message.attach(MIMEText(body, "plain"))

    try:
        # Conecta ao servidor SMTP e envia o e-mail
        with smtplib.SMTP(settings.EMAIL_HOST, settings.EMAIL_PORT) as server:
            server.starttls()
            server.login(settings.EMAIL_HOST_USER, settings.EMAIL_HOST_PASSWORD)
            server.send_message(message)

        print("E-mail enviado com sucesso para", receiver_email)

    except Exception as e:
        print("Erro ao enviar e-mail:", str(e))


def send_appointment_cancellation_email(
    client_email,
    salon_email,
    client_name,
    service_name,
    date_time,
    salon_name="Salonix",
):
    """
    Envia e-mail de cancelamento de agendamento para o cliente e o salão.

    Args:
        client_email (str): Email do cliente
        salon_email (str): Email do salão
        client_name (str): Nome do cliente
        service_name (str): Nome do serviço
        date_time (datetime): Data e hora do agendamento cancelado
    """
    subject = "Cancelamento de agendamento"
    sender_email = settings.EMAIL_HOST_USER

    formatted_date = date_time.strftime("%d/%m/%Y às %H:%M")

    body = f"""
    Olá {client_name},

    O seu agendamento para o serviço "{service_name}", marcado para {formatted_date}, foi cancelado com sucesso.

    Se você não solicitou esse cancelamento ou deseja remarcar, entre em contato conosco.

    Atenciosamente,
    Equipe {salon_name} 💈
    """

    # Cria a mensagem
    message = MIMEMultipart()
    message["From"] = sender_email
    message["To"] = client_email  # Isso será sobrescrito no loop abaixo
    message["Subject"] = subject
    message.attach(MIMEText(body, "plain"))

    try:
        with smtplib.SMTP(settings.EMAIL_HOST, settings.EMAIL_PORT) as server:
            server.starttls()
            server.login(settings.EMAIL_HOST_USER, settings.EMAIL_HOST_PASSWORD)

            for recipient in [client_email, salon_email]:
                message.replace_header("To", recipient)
                server.send_message(message)

        print(f"E-mail de cancelamento enviado para {client_email} e {salon_email}")

    except Exception as e:
        print("Erro ao enviar e-mail de cancelamento:", str(e))


def send_bulk_appointment_confirmation_email(
    to_email: str,
    client_name: str,
    items: list[dict],
    salon_name: str = "Salonix",
):
    """
    Envia um único e-mail consolidado com múltiplos agendamentos.

    items: lista de dicts com chaves mínimas:
        - service_name: str
        - start_time: datetime
        - professional_name: str (opcional)
    """
    subject = "Confirmação dos seus agendamentos"
    sender_email = settings.EMAIL_HOST_USER
    receiver_email = to_email

    lines = []  # texto plano
    html_lines = []  # HTML com âncoras
    for it in items:
        dt = it.get("start_time")
        formatted_date = (
            dt.strftime("%d/%m/%Y às %H:%M") if hasattr(dt, "strftime") else str(dt)
        )
        svc = it.get("service_name") or "Serviço"
        prof = it.get("professional_name")
        appt_id = it.get("appointment_id")

        # Link ICS por ocorrência, se configurado (público com token)
        ics_link = None
        try:
            base = getattr(settings, "ICS_BASE_URL", "")
            if base and appt_id:
                base = base.rstrip("/")
                # gerar token baseado em id e início do agendamento
                token = compute_public_ics_token(appt_id, dt)
                ics_link = (
                    f"{base}/api/public/appointments/{appt_id}/ics/?token={token}"
                )
        except Exception:
            ics_link = None

        if prof:
            if ics_link:
                lines.append(
                    f"• {formatted_date} — {svc} (com {prof}) — Adicionar ao calendário: {ics_link}"
                )
                html_lines.append(
                    f'<li>{formatted_date} — {svc} (com {prof}) — <a href="{ics_link}">Adicionar ao calendário</a></li>'
                )
            else:
                lines.append(f"• {formatted_date} — {svc} (com {prof})")
                html_lines.append(f"<li>{formatted_date} — {svc} (com {prof})</li>")
        else:
            if ics_link:
                lines.append(
                    f"• {formatted_date} — {svc} — Adicionar ao calendário: {ics_link}"
                )
                html_lines.append(
                    f'<li>{formatted_date} — {svc} — <a href="{ics_link}">Adicionar ao calendário</a></li>'
                )
            else:
                lines.append(f"• {formatted_date} — {svc}")
                html_lines.append(f"<li>{formatted_date} — {svc}</li>")

    joined_lines = "\n".join(lines)
    body = f"""
    Olá {client_name},

    Seguem as confirmações dos seus agendamentos:

    {joined_lines}

    Caso precise remarcar ou cancelar, entre em contato conosco com antecedência.

    Obrigado por escolher {salon_name}! 💈
    """
    # Versão HTML (com âncoras)
    html_list = "\n".join(html_lines)
    body_html = f"""
        <div style=\"font-family: Arial, sans-serif; font-size: 14px; color: #222;\">
          <p>Olá {client_name},</p>
          <p>Seguem as confirmações dos seus agendamentos:</p>
          <ul style=\"padding-left: 16px;\">
            {html_list}
          </ul>
          <p>Caso precise remarcar ou cancelar, entre em contato conosco com antecedência.</p>
          <p>Obrigado por escolher {salon_name}! 💈</p>
        </div>
        """

    # multipart/alternative: texto + HTML
    message = MIMEMultipart("alternative")
    message["From"] = sender_email
    message["To"] = receiver_email
    message["Subject"] = subject
    message.attach(MIMEText(body, "plain"))
    message.attach(MIMEText(body_html, "html"))

    try:
        with smtplib.SMTP(settings.EMAIL_HOST, settings.EMAIL_PORT) as server:
            server.starttls()
            server.login(settings.EMAIL_HOST_USER, settings.EMAIL_HOST_PASSWORD)
            server.send_message(message)
        print("E-mail consolidado enviado com sucesso para", receiver_email)
    except Exception as e:
        print("Erro ao enviar e-mail consolidado:", str(e))


def _build_unsubscribe_link(
    tenant_id: int, customer_id: int, channel: str = "email", purpose: str = "marketing"
) -> str:
    base = getattr(settings, "ICS_BASE_URL", "")
    try:
        token = signing.dumps(
            {
                "tenant_id": tenant_id,
                "customer_id": customer_id,
                "channel": channel,
                "purpose": purpose,
            },
            salt=UNSUBSCRIBE_TOKEN_SALT,
        )
        base = base.rstrip("/")
        return f"{base}/api/public/unsubscribe?token={token}"
    except Exception:
        return ""


def send_marketing_email(
    to_email: str,
    client_name: str,
    subject: str,
    body_text: str,
    *,
    tenant_id: int,
    customer_id: int,
    salon_name: str = "Salonix",
):
    """
    Envia e-mail de marketing com link de descadastro (unsubscribe).

    Inclui versão texto e HTML com link público tokenizado.
    """
    sender_email = settings.EMAIL_HOST_USER
    receiver_email = to_email

    unsubscribe_link = _build_unsubscribe_link(
        tenant_id, customer_id, "email", "marketing"
    )

    footer_plain = (
        f"\n\nSe não deseja receber comunicações de marketing do {salon_name}, "
        f"acesse: {unsubscribe_link}"
        if unsubscribe_link
        else ""
    )
    footer_html = (
        f'<p style="margin-top:16px;color:#555;">Se não deseja receber comunicações de marketing do {salon_name}, '
        f'<a href="{unsubscribe_link}">clique aqui</a>.</p>'
        if unsubscribe_link
        else ""
    )

    body_plain = f"{body_text}{footer_plain}"
    body_html = f"""
        <div style="font-family: Arial, sans-serif; font-size: 14px; color: #222;">
          <p>Olá {client_name},</p>
          <p>{body_text}</p>
          {footer_html}
        </div>
        """

    message = MIMEMultipart("alternative")
    message["From"] = sender_email
    message["To"] = receiver_email
    message["Subject"] = subject
    message.attach(MIMEText(body_plain, "plain"))
    message.attach(MIMEText(body_html, "html"))

    try:
        with smtplib.SMTP(settings.EMAIL_HOST, settings.EMAIL_PORT) as server:
            server.starttls()
            server.login(settings.EMAIL_HOST_USER, settings.EMAIL_HOST_PASSWORD)
            server.send_message(message)
        print("E-mail de marketing enviado com sucesso para", receiver_email)
    except Exception as e:
        print("Erro ao enviar e-mail de marketing:", str(e))
