import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from django.conf import settings


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

    lines = []
    for it in items:
        dt = it.get("start_time")
        formatted_date = (
            dt.strftime("%d/%m/%Y às %H:%M") if hasattr(dt, "strftime") else str(dt)
        )
        svc = it.get("service_name") or "Serviço"
        prof = it.get("professional_name")
        if prof:
            lines.append(f"• {formatted_date} — {svc} (com {prof})")
        else:
            lines.append(f"• {formatted_date} — {svc}")

    joined_lines = "\n".join(lines)
    body = f"""
    Olá {client_name},

    Seguem as confirmações dos seus agendamentos:

    {joined_lines}

    Caso precise remarcar ou cancelar, entre em contato conosco com antecedência.

    Obrigado por escolher {salon_name}! 💈
    """

    message = MIMEMultipart()
    message["From"] = sender_email
    message["To"] = receiver_email
    message["Subject"] = subject
    message.attach(MIMEText(body, "plain"))

    try:
        with smtplib.SMTP(settings.EMAIL_HOST, settings.EMAIL_PORT) as server:
            server.starttls()
            server.login(settings.EMAIL_HOST_USER, settings.EMAIL_HOST_PASSWORD)
            server.send_message(message)
        print("E-mail consolidado enviado com sucesso para", receiver_email)
    except Exception as e:
        print("Erro ao enviar e-mail consolidado:", str(e))
