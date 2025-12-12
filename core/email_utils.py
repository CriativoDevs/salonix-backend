import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from django.conf import settings
from django.utils.translation import gettext as _
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
    subject = _("Confirmação do seu agendamento")
    sender_email = settings.EMAIL_HOST_USER
    receiver_email = to_email

    formatted_date = date_time.strftime("%d/%m/%Y às %H:%M")

    body = (
        _("Olá %(client_name)s,")
        % {"client_name": client_name}
        + "\n\n"
        + _(
            'Seu agendamento para o serviço "%(service_name)s" foi confirmado com sucesso!'
        )
        % {"service_name": service_name}
        + "\n\n"
        + _("📅 Data e hora: %(formatted_date)s") % {"formatted_date": formatted_date}
        + "\n\n"
        + _(
            "Caso precise remarcar ou cancelar, entre em contato conosco com antecedência."
        )
        + "\n\n"
        + _("Obrigado por escolher %(salon_name)s! 💈") % {"salon_name": salon_name}
    )

    # Cria a mensagem
    message = MIMEMultipart()
    message["From"] = sender_email
    message["To"] = receiver_email
    message["Subject"] = subject

    message.attach(MIMEText(body, "plain"))

    # Guardas para ambientes de teste
    if getattr(settings, "EMAIL_DISABLE_OUTBOUND", False):
        print("[email] outbound disabled — confirmation to", receiver_email)
        return

    try:
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
    subject = _("Cancelamento de agendamento")
    sender_email = settings.EMAIL_HOST_USER

    formatted_date = date_time.strftime("%d/%m/%Y às %H:%M")

    body = (
        _("Olá %(client_name)s,")
        % {"client_name": client_name}
        + "\n\n"
        + _(
            'O seu agendamento para o serviço "%(service_name)s", marcado para %(formatted_date)s, foi cancelado com sucesso.'
        )
        % {"service_name": service_name, "formatted_date": formatted_date}
        + "\n\n"
        + _(
            "Se você não solicitou esse cancelamento ou deseja remarcar, entre em contato conosco."
        )
        + "\n\n"
        + _("Atenciosamente,")
        + "\n"
        + _("Equipe %(salon_name)s 💈") % {"salon_name": salon_name}
    )

    # Cria a mensagem
    message = MIMEMultipart()
    message["From"] = sender_email
    message["To"] = client_email  # Isso será sobrescrito no loop abaixo
    message["Subject"] = subject
    message.attach(MIMEText(body, "plain"))

    if getattr(settings, "EMAIL_DISABLE_OUTBOUND", False):
        print("[email] outbound disabled — cancellation to", client_email, salon_email)
        return

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
    subject = _("Confirmação dos seus agendamentos")
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
                    "• "
                    + f"{formatted_date} — {svc} (com {prof}) — "
                    + _("Adicionar ao calendário: %(link)s") % {"link": ics_link}
                )
                html_lines.append(
                    f'<li>{formatted_date} — {svc} (com {prof}) — <a href="{ics_link}">{_("Adicionar ao calendário")}</a></li>'
                )
            else:
                lines.append(f"• {formatted_date} — {svc} (com {prof})")
                html_lines.append(f"<li>{formatted_date} — {svc} (com {prof})</li>")
        else:
            if ics_link:
                lines.append(
                    "• "
                    + f"{formatted_date} — {svc} — "
                    + _("Adicionar ao calendário: %(link)s") % {"link": ics_link}
                )
                html_lines.append(
                    f'<li>{formatted_date} — {svc} — <a href="{ics_link}">{_("Adicionar ao calendário")}</a></li>'
                )
            else:
                lines.append(f"• {formatted_date} — {svc}")
                html_lines.append(f"<li>{formatted_date} — {svc}</li>")

    joined_lines = "\n".join(lines)
    body = (
        _("Olá %(client_name)s,")
        % {"client_name": client_name}
        + "\n\n"
        + _("Seguem as confirmações dos seus agendamentos:")
        + "\n\n"
        + joined_lines
        + "\n\n"
        + _(
            "Caso precise remarcar ou cancelar, entre em contato conosco com antecedência."
        )
        + "\n\n"
        + _("Obrigado por escolher %(salon_name)s! 💈") % {"salon_name": salon_name}
    )
    # Versão HTML (com âncoras)
    html_list = "\n".join(html_lines)
    body_html = f"""
        <div style=\"font-family: Arial, sans-serif; font-size: 14px; color: #222;\">
          <p>{_("Olá %(client_name)s,") % {"client_name": client_name}}</p>
          <p>{_("Seguem as confirmações dos seus agendamentos:")}</p>
          <ul style=\"padding-left: 16px;\">
            {html_list}
          </ul>
          <p>{_("Caso precise remarcar ou cancelar, entre em contato conosco com antecedência.")}</p>
          <p>{_("Obrigado por escolher %(salon_name)s! 💈") % {"salon_name": salon_name}}</p>
        </div>
        """

    # multipart/alternative: texto + HTML
    message = MIMEMultipart("alternative")
    message["From"] = sender_email
    message["To"] = receiver_email
    message["Subject"] = subject
    message.attach(MIMEText(body, "plain"))
    message.attach(MIMEText(body_html, "html"))

    if getattr(settings, "EMAIL_DISABLE_OUTBOUND", False):
        print("[email] outbound disabled — bulk confirmation to", receiver_email)
        return

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
        "\n\n"
        + _(
            "Se não deseja receber comunicações de marketing do %(salon_name)s, acesse: %(link)s"
        )
        % {"salon_name": salon_name, "link": unsubscribe_link}
        if unsubscribe_link
        else ""
    )
    footer_html = (
        f'<p style="margin-top:16px;color:#555;">{_("Se não deseja receber comunicações de marketing do %(salon_name)s, ") % {"salon_name": salon_name}}'
        + f'<a href="{unsubscribe_link}">{_("clique aqui")}</a>.</p>'
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

    if getattr(settings, "EMAIL_DISABLE_OUTBOUND", False):
        print("[email] outbound disabled — marketing to", receiver_email)
        return

    try:
        with smtplib.SMTP(settings.EMAIL_HOST, settings.EMAIL_PORT) as server:
            server.starttls()
            server.login(settings.EMAIL_HOST_USER, settings.EMAIL_HOST_PASSWORD)
            server.send_message(message)
        print("E-mail de marketing enviado com sucesso para", receiver_email)
    except Exception as e:
        print("Erro ao enviar e-mail de marketing:", str(e))


def send_staff_invite_email(
    to_email: str,
    accept_url: str,
    salon_name: str = "Salonix",
    inviter_name: str | None = None,
):
    subject = "Convite para acessar o painel do salão"
    sender_email = settings.EMAIL_HOST_USER
    receiver_email = to_email

    inviter_line = (
        f"{inviter_name} convidou você para acessar o painel do {salon_name}."
        if inviter_name
        else f"Você foi convidado(a) para acessar o painel do {salon_name}."
    )

    body_plain = f"""
Olá,

{inviter_line}

Para ativar seu acesso, defina sua senha clicando no link abaixo:
{accept_url}

Se você não esperava este convite, ignore este e-mail.

Obrigado,
Equipe {salon_name}
"""

    body_html = f"""
        <div style="font-family: Arial, sans-serif; font-size: 14px; color: #222;">
          <p>{_("Olá,")}</p>
          <p>{inviter_line}</p>
          <p>{_("Para ativar seu acesso, defina sua senha clicando no link abaixo:")}</p>
          <p><a href="{accept_url}" target="_blank" rel="noopener">{_("Ativar acesso")}</a></p>
          <p style="font-size:12px;color:#555">{_("Se você não esperava este convite, ignore este e-mail.")}</p>
          <p>{_("Obrigado,")}<br/>{_("Equipe %(salon_name)s") % {"salon_name": salon_name}}</p>
        </div>
    """

    message = MIMEMultipart("alternative")
    message["From"] = sender_email
    message["To"] = receiver_email
    message["Subject"] = subject
    message.attach(MIMEText(body_plain, "plain"))
    message.attach(MIMEText(body_html, "html"))

    if getattr(settings, "EMAIL_DISABLE_OUTBOUND", False):
        print("[email] outbound disabled — staff invite to", receiver_email)
        return True

    try:
        with smtplib.SMTP(settings.EMAIL_HOST, settings.EMAIL_PORT) as server:
            server.starttls()
            server.login(settings.EMAIL_HOST_USER, settings.EMAIL_HOST_PASSWORD)
            server.send_message(message)
        print("E-mail de convite de staff enviado para", receiver_email)
        return True
    except Exception as e:
        print("Erro ao enviar e-mail de convite de staff:", str(e))
        return False


def send_staff_access_link_email(
    to_email: str,
    access_url: str,
    salon_name: str = "Salonix",
):
    subject = _("Acesso ao painel")
    sender_email = settings.EMAIL_HOST_USER
    receiver_email = to_email

    body_plain = f"""
Use o link abaixo para acessar o painel redefinindo sua senha:
{access_url}

Se você não solicitou esta ação, ignore este e-mail.
"""

    body_html = f"""
        <div style="font-family: Arial, sans-serif; font-size: 14px; color: #222;">
          <p>{_("Use o link abaixo para acessar o painel redefinindo sua senha:")}</p>
          <p><a href="{access_url}" target="_blank" rel="noopener">{_("Acessar")}</a></p>
          <p style="font-size:12px;color:#555">{_("Se você não solicitou esta ação, ignore este e-mail.")}</p>
          <p>{_("Obrigado,")}<br/>{_("Equipe %(salon_name)s") % {"salon_name": salon_name}}</p>
        </div>
    """

    message = MIMEMultipart("alternative")
    message["From"] = sender_email
    message["To"] = receiver_email
    message["Subject"] = subject
    message.attach(MIMEText(body_plain, "plain"))
    message.attach(MIMEText(body_html, "html"))

    if getattr(settings, "EMAIL_DISABLE_OUTBOUND", False):
        print("[email] outbound disabled — access link to", receiver_email)
        return True

    try:
        with smtplib.SMTP(settings.EMAIL_HOST, settings.EMAIL_PORT) as server:
            server.starttls()
            server.login(settings.EMAIL_HOST_USER, settings.EMAIL_HOST_PASSWORD)
            server.send_message(message)
        print("E-mail de acesso enviado para", receiver_email)
        return True
    except Exception as e:
        print("Erro ao enviar e-mail de acesso:", str(e))
        return False
