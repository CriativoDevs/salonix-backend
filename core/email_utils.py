import logging
import threading
import time
from django.conf import settings
from django.core.cache import cache
from django.db import connection
from django.utils.translation import gettext as _
from django.core import signing
from django.core.mail import EmailMultiAlternatives
from notifications.views import UNSUBSCRIBE_TOKEN_SALT
from core.utils.ics import compute_public_ics_token
import secrets

logger = logging.getLogger(__name__)


def _send_email_safe(
    subject: str,
    body_plain: str,
    body_html: str | None,
    to_emails: list[str] | str,
    reply_to: list[str] | None = None,
) -> bool:
    """
    Helper interno para enviar e-mails de forma assíncrona usando Threads.
    Evita travar a resposta HTTP enquanto o servidor SMTP processa o envio.
    """
    if getattr(settings, "EMAIL_DISABLE_OUTBOUND", False):
        # Permitimos o bypass para testes que precisam validar threads
        if not subject.startswith("TEST_THREAD_BYPASS"):
            logger.info(
                f"[email] outbound disabled — would send '{subject}' to {to_emails}"
            )
            return True

    if isinstance(to_emails, str):
        to_emails = [to_emails]

    # Reply-To padrão (no-reply respondível) quando o chamador não especifica um.
    if reply_to is None:
        default_reply_to = getattr(settings, "EMAIL_REPLY_TO", "") or ""
        if default_reply_to:
            reply_to = [default_reply_to]

    def send_action():
        # Máximo de tentativas para lidar com erros intermitentes de rede (Errno 101)
        max_retries = 3
        retry_delay = 2  # segundos

        for attempt in range(max_retries):
            try:
                email = EmailMultiAlternatives(
                    subject=subject,
                    body=body_plain,
                    from_email=settings.DEFAULT_FROM_EMAIL or settings.EMAIL_HOST_USER,
                    to=to_emails,
                    reply_to=reply_to,
                )
                if body_html:
                    email.attach_alternative(body_html, "text/html")

                email.send(fail_silently=False)
                logger.info(
                    f"E-mail '{subject}' enviado com sucesso via Thread para {to_emails} (Tentativa {attempt + 1})"
                )
                break  # Sucesso, sai do loop de retries
            except Exception as e:
                is_last_attempt = attempt == max_retries - 1
                error_msg = f"Erro ao enviar e-mail '{subject}' via Thread (Tentativa {attempt + 1}/{max_retries}): {str(e)}"

                if is_last_attempt:
                    logger.error(
                        error_msg,
                        exc_info=True,
                        extra={
                            "email_config": {
                                "host": settings.EMAIL_HOST,
                                "port": settings.EMAIL_PORT,
                                "backend": settings.EMAIL_BACKEND,
                                "user": settings.EMAIL_HOST_USER,
                            }
                        },
                    )
                else:
                    logger.warning(
                        f"{error_msg}. Tentando novamente em {retry_delay}s..."
                    )
                    time.sleep(retry_delay)
            finally:
                # Garante que a conexão com o banco de dados desta thread seja fechada
                # Isso evita vazamento de conexões e erros de 'Network is unreachable'
                # por threads penduradas segurando recursos do SO.
                connection.close()

    # Dispara o envio em uma thread separada para não bloquear a resposta da API
    thread = threading.Thread(target=send_action)
    thread.start()

    # Retornamos True imediatamente para liberar a requisição HTTP
    return True


def send_appointment_confirmation_email(
    to_email, client_name, service_name, date_time, salon_name="TimelyOne"
):
    """
    Envia e-mail de confirmação de agendamento.
    """
    subject = _("Confirmação do seu agendamento")
    formatted_date = date_time.strftime("%d/%m/%Y às %H:%M")

    body = (
        _("Olá %(client_name)s,") % {"client_name": client_name}
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

    # Opcional: Adicionar versão HTML simples se desejado, mas mantendo compatibilidade com texto plano
    # Por enquanto mantemos texto plano como principal, mas podemos enriquecer depois.
    # O código original tinha MIMEText(body, "plain"), então vamos manter assim.

    _send_email_safe(subject, body, None, to_email)


def send_appointment_cancellation_email(
    client_email,
    salon_email,
    client_name,
    service_name,
    date_time,
    salon_name="TimelyOne",
):
    """
    Envia e-mail de cancelamento de agendamento para o cliente e o salão.
    """
    subject = _("Cancelamento de agendamento")
    formatted_date = date_time.strftime("%d/%m/%Y às %H:%M")

    body = (
        _("Olá %(client_name)s,") % {"client_name": client_name}
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

    # Envia para ambos
    _send_email_safe(subject, body, None, [client_email, salon_email])


def send_staff_access_link_email(to_email, access_url, salon_name):
    """
    Envia e-mail com link de acesso rápido para staff.
    """
    subject = _("Seu link de acesso ao %(salon_name)s") % {"salon_name": salon_name}

    body = (
        _("Olá,")
        + "\n\n"
        + _("Você solicitou um link de acesso para o salão %(salon_name)s.")
        % {"salon_name": salon_name}
        + "\n\n"
        + _("Clique no link abaixo para acessar:")
        + "\n"
        + access_url
        + "\n\n"
        + _("Este link expira em breve.")
        + "\n\n"
        + _("Se você não solicitou este acesso, ignore este e-mail.")
    )

    return _send_email_safe(subject, body, None, to_email)


def send_bulk_appointment_confirmation_email(
    to_email: str,
    client_name: str,
    items: list[dict],
    salon_name: str = "TimelyOne",
):
    """
    Envia um único e-mail consolidado com múltiplos agendamentos.
    """
    subject = _("Confirmação dos seus agendamentos")

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
                # Gera token real e publica apenas um rid opaco com TTL no e-mail.
                token = compute_public_ics_token(appt_id, dt)
                rid = secrets.token_urlsafe(18)
                rid_ttl_seconds = int(
                    getattr(settings, "ICS_EMAIL_RID_TTL_SECONDS", 7 * 24 * 60 * 60)
                )
                cache.set(
                    f"ics:rid:{rid}",
                    {
                        "appointment_id": int(appt_id),
                        "token": token,
                    },
                    timeout=rid_ttl_seconds,
                )
                ics_link = f"{base}/api/public/appointments/{appt_id}/ics/?rid={rid}"
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
        _("Olá %(client_name)s,") % {"client_name": client_name}
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

    _send_email_safe(subject, body, body_html, to_email)


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
    salon_name: str = "TimelyOne",
):
    """
    Envia e-mail de marketing com link de descadastro (unsubscribe).
    """
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

    _send_email_safe(subject, body_plain, body_html, to_email)


def send_staff_invite_email(
    to_email: str,
    accept_url: str,
    salon_name: str = "TimelyOne",
    inviter_name: str | None = None,
):
    subject = "Convite para acessar o painel do salão"

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

    return _send_email_safe(subject, body_plain, body_html, to_email)


def send_account_cancellation_email(
    tenant,
    owner_user,
    reactivation_url: str,
):
    """
    Envia email de confirmação de cancelamento de conta (BE-ACCOUNT-CANCEL #396).

    Args:
        tenant: Instância do Tenant cancelado
        owner_user: Usuário owner que cancelou
        reactivation_url: URL completa para reativar a conta
    """
    subject = "Conta cancelada - TimelyOne"

    deletion_date_formatted = tenant.scheduled_deletion_at.strftime("%d/%m/%Y")

    body_plain = f"""
Olá {owner_user.first_name or owner_user.username},

Sua conta "{tenant.name}" foi cancelada com sucesso.

📅 Data de cancelamento: {tenant.cancelled_at.strftime("%d/%m/%Y às %H:%M")}
🗑️ Exclusão permanente em: {deletion_date_formatted}

O que acontece agora?
• Seu acesso e de todos os membros da equipe foi bloqueado
• Suas assinaturas Stripe foram canceladas (você não será mais cobrado)
• Seus dados serão mantidos até {deletion_date_formatted}
• Após essa data, todos os dados serão excluídos permanentemente

Mudou de ideia?
Você pode reativar sua conta a qualquer momento até {deletion_date_formatted}:
{reactivation_url}

Se tiver alguma dúvida ou feedback, responda este email.

Obrigado por ter usado o TimelyOne,
Equipe TimelyOne
"""

    body_html = f"""
        <div style="font-family: Arial, sans-serif; font-size: 14px; color: #222; max-width: 600px; margin: 0 auto;">
          <h2 style="color: #d9534f;">Conta cancelada</h2>
          
          <p>Olá <strong>{owner_user.first_name or owner_user.username}</strong>,</p>
          
          <p>Sua conta "<strong>{tenant.name}</strong>" foi cancelada com sucesso.</p>
          
          <div style="background-color: #f8f9fa; padding: 15px; border-left: 4px solid #d9534f; margin: 20px 0;">
            <p style="margin: 5px 0;"><strong>📅 Data de cancelamento:</strong> {tenant.cancelled_at.strftime("%d/%m/%Y às %H:%M")}</p>
            <p style="margin: 5px 0;"><strong>🗑️ Exclusão permanente em:</strong> {deletion_date_formatted}</p>
          </div>
          
          <h3 style="color: #333; font-size: 16px;">O que acontece agora?</h3>
          <ul style="line-height: 1.8;">
            <li>Seu acesso e de todos os membros da equipe foi <strong>bloqueado</strong></li>
            <li>Suas assinaturas Stripe foram <strong>canceladas</strong> (você não será mais cobrado)</li>
            <li>Seus dados serão mantidos até <strong>{deletion_date_formatted}</strong></li>
            <li>Após essa data, todos os dados serão <strong>excluídos permanentemente</strong></li>
          </ul>
          
          <div style="background-color: #d1ecf1; padding: 15px; border-left: 4px solid #0c5460; margin: 20px 0;">
            <h3 style="color: #0c5460; margin-top: 0; font-size: 16px;">Mudou de ideia?</h3>
            <p>Você pode reativar sua conta a qualquer momento até <strong>{deletion_date_formatted}</strong>:</p>
            <p style="text-align: center; margin: 15px 0;">
              <a href="{reactivation_url}" 
                 style="display: inline-block; padding: 12px 24px; background-color: #28a745; color: white; text-decoration: none; border-radius: 5px; font-weight: bold;">
                Reativar minha conta
              </a>
            </p>
          </div>
          
          <p style="margin-top: 30px; color: #666; font-size: 12px;">
            Se tiver alguma dúvida ou feedback, responda este email.
          </p>
          
          <p style="margin-top: 20px;">
            Obrigado por ter usado o TimelyOne,<br/>
            <strong>Equipe TimelyOne</strong>
          </p>
        </div>
    """

    return _send_email_safe(subject, body_plain, body_html, owner_user.email)


def send_deletion_reminder_email(
    tenant,
    owner_user,
    reactivation_url: str,
    days_remaining: int = 7,
):
    """
    Envia lembrete de exclusão iminente (BE-ACCOUNT-CANCEL #396).

    Args:
        tenant: Instância do Tenant a ser deletado
        owner_user: Usuário owner
        reactivation_url: URL completa para reativar a conta
        days_remaining: Dias restantes até exclusão
    """
    subject = f"⚠️ Sua conta será excluída em {days_remaining} dias - TimelyOne"

    deletion_date_formatted = tenant.scheduled_deletion_at.strftime("%d/%m/%Y")

    body_plain = f"""
Olá {owner_user.first_name or owner_user.username},

Este é um lembrete de que sua conta "{tenant.name}" será excluída permanentemente em {days_remaining} dias.

🗑️ Data de exclusão: {deletion_date_formatted}

O que será excluído?
• Todos os agendamentos e histórico
• Dados de clientes e profissionais
• Relatórios e estatísticas
• Configurações personalizadas

⚠️ Esta ação é IRREVERSÍVEL após {deletion_date_formatted}.

Quer manter sua conta?
Reative agora mesmo:
{reactivation_url}

Se você realmente deseja cancelar, não é necessário fazer nada. Seus dados serão automaticamente excluídos na data mencionada.

Equipe TimelyOne
"""

    body_html = f"""
        <div style="font-family: Arial, sans-serif; font-size: 14px; color: #222; max-width: 600px; margin: 0 auto;">
          <div style="background-color: #fff3cd; border-left: 4px solid #ffc107; padding: 15px; margin-bottom: 20px;">
            <h2 style="color: #856404; margin-top: 0;">⚠️ Lembrete importante</h2>
          </div>
          
          <p>Olá <strong>{owner_user.first_name or owner_user.username}</strong>,</p>
          
          <p>Este é um lembrete de que sua conta "<strong>{tenant.name}</strong>" será excluída permanentemente em <strong>{days_remaining} dias</strong>.</p>
          
          <div style="background-color: #f8d7da; padding: 15px; border-left: 4px solid #d9534f; margin: 20px 0; text-align: center;">
            <p style="margin: 0; font-size: 18px; color: #721c24;">
              <strong>🗑️ Data de exclusão: {deletion_date_formatted}</strong>
            </p>
          </div>
          
          <h3 style="color: #333; font-size: 16px;">O que será excluído?</h3>
          <ul style="line-height: 1.8;">
            <li>Todos os <strong>agendamentos e histórico</strong></li>
            <li>Dados de <strong>clientes e profissionais</strong></li>
            <li><strong>Relatórios e estatísticas</strong></li>
            <li><strong>Configurações personalizadas</strong></li>
          </ul>
          
          <div style="background-color: #f8d7da; padding: 10px; border-radius: 5px; margin: 20px 0;">
            <p style="margin: 0; color: #721c24; font-weight: bold; text-align: center;">
              ⚠️ Esta ação é IRREVERSÍVEL após {deletion_date_formatted}
            </p>
          </div>
          
          <div style="background-color: #d1ecf1; padding: 15px; border-left: 4px solid #0c5460; margin: 20px 0;">
            <h3 style="color: #0c5460; margin-top: 0; font-size: 16px;">Quer manter sua conta?</h3>
            <p style="text-align: center; margin: 15px 0;">
              <a href="{reactivation_url}" 
                 style="display: inline-block; padding: 12px 24px; background-color: #28a745; color: white; text-decoration: none; border-radius: 5px; font-weight: bold; font-size: 16px;">
                Reativar minha conta agora
              </a>
            </p>
          </div>
          
          <p style="margin-top: 30px; color: #666; font-size: 12px;">
            Se você realmente deseja cancelar, não é necessário fazer nada. Seus dados serão automaticamente excluídos na data mencionada.
          </p>
          
          <p style="margin-top: 20px;">
            <strong>Equipe TimelyOne</strong>
          </p>
        </div>
    """

    return _send_email_safe(subject, body_plain, body_html, owner_user.email)


def send_account_reactivation_email(
    tenant,
    owner_user,
):
    """
    Envia confirmação de reativação de conta (BE-ACCOUNT-CANCEL #396).

    Args:
        tenant: Instância do Tenant reativado
        owner_user: Usuário owner que reativou
    """
    subject = "✅ Conta reativada com sucesso - TimelyOne"

    body_plain = f"""
Olá {owner_user.first_name or owner_user.username},

Sua conta "{tenant.name}" foi reativada com sucesso!

✅ Seu acesso foi restaurado
✅ Todos os dados foram preservados
✅ Sua equipe pode acessar novamente

O que acontece agora?
• Você e sua equipe podem fazer login normalmente
• Todos os dados permanecem intactos
• Para retomar as assinaturas, acesse as configurações de billing

Bem-vindo de volta! 🎉

Se precisar de ajuda, estamos à disposição.

Equipe TimelyOne
"""

    body_html = f"""
        <div style="font-family: Arial, sans-serif; font-size: 14px; color: #222; max-width: 600px; margin: 0 auto;">
          <div style="background-color: #d4edda; border-left: 4px solid #28a745; padding: 15px; margin-bottom: 20px;">
            <h2 style="color: #155724; margin-top: 0;">✅ Conta reativada com sucesso</h2>
          </div>
          
          <p>Olá <strong>{owner_user.first_name or owner_user.username}</strong>,</p>
          
          <p>Sua conta "<strong>{tenant.name}</strong>" foi reativada com sucesso!</p>
          
          <div style="background-color: #d4edda; padding: 15px; border-radius: 5px; margin: 20px 0;">
            <ul style="list-style: none; padding: 0; margin: 0; line-height: 1.8;">
              <li>✅ Seu acesso foi <strong>restaurado</strong></li>
              <li>✅ Todos os dados foram <strong>preservados</strong></li>
              <li>✅ Sua equipe pode <strong>acessar novamente</strong></li>
            </ul>
          </div>
          
          <h3 style="color: #333; font-size: 16px;">O que acontece agora?</h3>
          <ul style="line-height: 1.8;">
            <li>Você e sua equipe podem fazer <strong>login normalmente</strong></li>
            <li>Todos os dados permanecem <strong>intactos</strong></li>
            <li>Para retomar as assinaturas, acesse as <strong>configurações de billing</strong></li>
          </ul>
          
          <div style="text-align: center; margin: 30px 0;">
            <p style="font-size: 24px; margin: 0;">🎉</p>
            <p style="font-size: 18px; color: #28a745; font-weight: bold; margin: 10px 0;">
              Bem-vindo de volta!
            </p>
          </div>
          
          <p style="margin-top: 30px; color: #666; font-size: 12px;">
            Se precisar de ajuda, estamos à disposição.
          </p>
          
          <p style="margin-top: 20px;">
            <strong>Equipe TimelyOne</strong>
          </p>
        </div>
    """

    return _send_email_safe(subject, body_plain, body_html, owner_user.email)
