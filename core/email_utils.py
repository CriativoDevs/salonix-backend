import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from django.conf import settings


def send_appointment_confirmation_email(to_email, client_name, service_name, date_time):
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

    Obrigado por escolher o Salonix! 💈
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
    client_email, salon_email, client_name, service_name, date_time
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
    Equipe Salonix 💈
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
