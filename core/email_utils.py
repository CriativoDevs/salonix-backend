"""
Envio de emails transacionais/automáticos da plataforma.

Mapeamento de remetente (from_email) por tipo de email — BE-MARKETING-02 (#477).
O mapeamento completo e as razões de cada bucket estão documentados junto às
settings EMAIL_FROM_* em salonix_backend/settings.py; resumo:
  EMAIL_FROM_BOOKING      -> confirmação/alteração de agendamento
  EMAIL_FROM_CANCELLATION -> cancelamento de agendamento
  EMAIL_FROM_SUPPORT      -> suporte, feedback da plataforma, e demais emails
                             transacionais não cobertos pelos remetentes acima
                             (também o default de _send_email_safe quando a
                             função chamadora não passa from_email explícito)
  EMAIL_FROM_BILLING      -> faturação/subscrição (Stripe) e ciclo de vida da
                             conta

`timelyone@timelyone.today` (DEFAULT_FROM_EMAIL) é reservado ao contacto geral
da landing page e nunca deve ser usado como remetente automático.
"""

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
    from_email: str | None = None,
) -> bool:
    """
    Helper interno para enviar e-mails de forma assíncrona usando Threads.
    Evita travar a resposta HTTP enquanto o servidor SMTP processa o envio.

    `from_email` deve ser passado explicitamente pela função chamadora sempre
    que o tipo de email tiver um remetente mapeado (ver EMAIL_FROM_* em
    settings.py, BE-MARKETING-02 #477). Quando omitido, cai em
    EMAIL_FROM_SUPPORT — nunca em DEFAULT_FROM_EMAIL, que é reservado ao
    contacto geral e não deve responder por emails automáticos.
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

    resolved_from_email = (
        from_email
        or getattr(settings, "EMAIL_FROM_SUPPORT", "")
        or settings.DEFAULT_FROM_EMAIL
        or settings.EMAIL_HOST_USER
    )

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
                    from_email=resolved_from_email,
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
    to_email,
    client_name,
    service_name,
    date_time,
    salon_name="TimelyOne",
    appointment_id=None,
):
    """
    Envia e-mail de confirmação de agendamento.
    """
    subject = _("Confirmação do seu agendamento")
    formatted_date = date_time.strftime("%d/%m/%Y às %H:%M")

    # Link ICS (público, com token), mesmo padrão usado na confirmação em massa.
    ics_link = None
    try:
        base = getattr(settings, "ICS_BASE_URL", "")
        if base and appointment_id:
            base = base.rstrip("/")
            token = compute_public_ics_token(appointment_id, date_time)
            rid = secrets.token_urlsafe(18)
            rid_ttl_seconds = int(
                getattr(settings, "ICS_EMAIL_RID_TTL_SECONDS", 7 * 24 * 60 * 60)
            )
            cache.set(
                f"ics:rid:{rid}",
                {"appointment_id": int(appointment_id), "token": token},
                timeout=rid_ttl_seconds,
            )
            ics_link = f"{base}/api/public/appointments/{appointment_id}/ics/?rid={rid}"
    except Exception:
        ics_link = None

    body = (
        _("Olá %(client_name)s,") % {"client_name": client_name}
        + "\n\n"
        + _(
            'Seu agendamento para o serviço "%(service_name)s" foi confirmado com sucesso!'
        )
        % {"service_name": service_name}
        + "\n\n"
        + _("📅 Data e hora: %(formatted_date)s") % {"formatted_date": formatted_date}
    )
    if ics_link:
        body += "\n\n" + _("Adicionar ao calendário: %(link)s") % {"link": ics_link}
    body += (
        "\n\n"
        + _(
            "Caso precise remarcar ou cancelar, entre em contato conosco com antecedência."
        )
        + "\n\n"
        + _("Obrigado por escolher %(salon_name)s! 💈") % {"salon_name": salon_name}
    )

    calendar_html = (
        f'<p><a href="{ics_link}">{_("Adicionar ao calendário")}</a></p>'
        if ics_link
        else ""
    )
    body_html = f"""
        <div style="font-family: Arial, sans-serif; font-size: 14px; color: #222;">
          <p>{_("Olá %(client_name)s,") % {"client_name": client_name}}</p>
          <p>{
        _('Seu agendamento para o serviço "%(service_name)s" foi confirmado com sucesso!')
        % {"service_name": service_name}
    }</p>
          <p>{_("📅 Data e hora: %(formatted_date)s") % {"formatted_date": formatted_date}}</p>
          {calendar_html}
          <p>{_("Caso precise remarcar ou cancelar, entre em contato conosco com antecedência.")}</p>
          <p>{_("Obrigado por escolher %(salon_name)s! 💈") % {"salon_name": salon_name}}</p>
        </div>
        """

    _send_email_safe(
        subject,
        body,
        body_html,
        to_email,
        from_email=getattr(settings, "EMAIL_FROM_BOOKING", None),
    )


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
    _send_email_safe(
        subject,
        body,
        None,
        [client_email, salon_email],
        from_email=getattr(settings, "EMAIL_FROM_CANCELLATION", None),
    )


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

    return _send_email_safe(
        subject,
        body,
        None,
        to_email,
        from_email=getattr(settings, "EMAIL_FROM_SUPPORT", None),
    )


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

    _send_email_safe(
        subject,
        body,
        body_html,
        to_email,
        from_email=getattr(settings, "EMAIL_FROM_BOOKING", None),
    )


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

    _send_email_safe(
        subject,
        body_plain,
        body_html,
        to_email,
        from_email=getattr(settings, "EMAIL_FROM_SUPPORT", None),
    )


def _store_links() -> tuple[str, str]:
    """URLs canonicos das stores (iOS, Android)."""
    return (
        getattr(settings, "STORE_IOS_URL", ""),
        getattr(settings, "STORE_ANDROID_URL", ""),
    )


def store_badges_html() -> str:
    """Bloco HTML com os 2 badges das stores (PNG via URL absoluto)."""
    ios_url, android_url = _store_links()
    base = getattr(settings, "STORE_BADGES_BASE_URL", "").rstrip("/")
    ios_alt = _("Transferir na App Store")
    android_alt = _("Disponível no Google Play")
    return f"""
        <div style="margin-top:24px;">
          <p style="font-size:13px;color:#555;margin:0 0 8px;">{_("Instala a app TimelyOne:")}</p>
          <a href="{ios_url}" target="_blank" rel="noopener" style="text-decoration:none;margin-right:8px;">
            <img src="{base}/app-store-pt.png" alt="{ios_alt}" height="40" style="height:40px;border:0;" />
          </a>
          <a href="{android_url}" target="_blank" rel="noopener" style="text-decoration:none;">
            <img src="{base}/google-play-pt.png" alt="{android_alt}" height="40" style="height:40px;border:0;" />
          </a>
        </div>
    """


def store_badges_text() -> str:
    """Variante texto-plano: os 2 URLs como links de texto (fallback)."""
    ios_url, android_url = _store_links()
    return (
        f"\n{_('Instala a app TimelyOne:')}\n"
        f"- {_('App Store')}: {ios_url}\n"
        f"- {_('Google Play')}: {android_url}\n"
    )


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
{store_badges_text()}"""

    body_html = f"""
        <div style="font-family: Arial, sans-serif; font-size: 14px; color: #222;">
          <p>{_("Olá,")}</p>
          <p>{inviter_line}</p>
          <p>{_("Para ativar seu acesso, defina sua senha clicando no link abaixo:")}</p>
          <p><a href="{accept_url}" target="_blank" rel="noopener">{_("Ativar acesso")}</a></p>
          <p style="font-size:12px;color:#555">{_("Se você não esperava este convite, ignore este e-mail.")}</p>
          <p>{_("Obrigado,")}<br/>{_("Equipe %(salon_name)s") % {"salon_name": salon_name}}</p>
          {store_badges_html()}
        </div>
    """

    return _send_email_safe(
        subject,
        body_plain,
        body_html,
        to_email,
        from_email=getattr(settings, "EMAIL_FROM_SUPPORT", None),
    )


def send_tenant_welcome_email(
    to_email: str,
    owner_name: str | None = None,
    salon_name: str = "TimelyOne",
):
    """Email de boas-vindas no registo do tenant, com badges das stores."""
    subject = _("Bem-vindo ao TimelyOne")
    greeting = (
        _("Olá %(name)s,") % {"name": owner_name} if owner_name else _("Olá,")
    )

    body_plain = f"""
{greeting}

{_("A tua conta %(salon_name)s foi criada com sucesso. Bem-vindo ao TimelyOne!") % {"salon_name": salon_name}}

{_("Primeiros passos: configura os teus serviços, a tua equipa e o horário de funcionamento, e começa a receber agendamentos.")}
{store_badges_text()}
{_("Obrigado,")}
{_("Equipe TimelyOne")}
"""

    body_html = f"""
        <div style="font-family: Arial, sans-serif; font-size: 14px; color: #222;">
          <p>{greeting}</p>
          <p>{_("A tua conta %(salon_name)s foi criada com sucesso. Bem-vindo ao TimelyOne!") % {"salon_name": salon_name}}</p>
          <p>{_("Primeiros passos: configura os teus serviços, a tua equipa e o horário de funcionamento, e começa a receber agendamentos.")}</p>
          {store_badges_html()}
          <p>{_("Obrigado,")}<br/>{_("Equipe TimelyOne")}</p>
        </div>
    """

    return _send_email_safe(
        subject,
        body_plain,
        body_html,
        to_email,
        from_email=getattr(settings, "EMAIL_FROM_SUPPORT", None),
    )


def send_voucher_email(
    to_email: str,
    client_name: str,
    voucher_code: str,
    voucher_type: str,
    voucher_value=None,
    service_name: str | None = None,
    valid_until=None,
    salon_name: str = "TimelyOne",
):
    """
    Envia e-mail com um voucher atribuído a um cliente (BE-VOUCHER-04, #473).

    Disparado a partir de `vouchers.tasks.send_voucher_email_task`, nunca
    diretamente pela view (envio é sempre assíncrono).
    """
    subject = _("Você recebeu um voucher de %(salon_name)s") % {
        "salon_name": salon_name
    }

    if voucher_type == "percent":
        value_line = _("Desconto: %(value)s%%") % {"value": voucher_value}
    elif voucher_type == "fixed":
        value_line = _("Desconto: €%(value)s") % {"value": voucher_value}
    else:
        value_line = _("Serviço grátis: %(service)s") % {
            "service": service_name or ""
        }

    validity_line = (
        _("Válido até: %(date)s") % {"date": valid_until.strftime("%d/%m/%Y")}
        if valid_until
        else _("Sem data de expiração")
    )

    body_plain = f"""{_("Olá %(name)s,") % {"name": client_name}}

{_("Tens um voucher de %(salon_name)s à tua espera!") % {"salon_name": salon_name}}

{_("Código")}: {voucher_code}
{value_line}
{validity_line}

{_("Apresenta este código no teu próximo agendamento.")}

{_("Obrigado,")}
{_("Equipe %(salon_name)s") % {"salon_name": salon_name}}
"""

    body_html = f"""
        <div style="font-family: Arial, sans-serif; font-size: 14px; color: #222;">
          <p>{_("Olá %(name)s,") % {"name": client_name}}</p>
          <p>{_("Tens um voucher de %(salon_name)s à tua espera!") % {"salon_name": salon_name}}</p>
          <div style="background:#f8f9fa;border:1px dashed #999;padding:12px 16px;margin:16px 0;">
            <p style="margin:4px 0;"><strong>{_("Código")}:</strong> {voucher_code}</p>
            <p style="margin:4px 0;">{value_line}</p>
            <p style="margin:4px 0;">{validity_line}</p>
          </div>
          <p>{_("Apresenta este código no teu próximo agendamento.")}</p>
          <p>{_("Obrigado,")}<br/>{_("Equipe %(salon_name)s") % {"salon_name": salon_name}}</p>
        </div>
        """

    return _send_email_safe(
        subject,
        body_plain,
        body_html,
        to_email,
        from_email=getattr(settings, "EMAIL_FROM_SUPPORT", None),
    )


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

    return _send_email_safe(
        subject,
        body_plain,
        body_html,
        owner_user.email,
        from_email=getattr(settings, "EMAIL_FROM_BILLING", None),
    )


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

    return _send_email_safe(
        subject,
        body_plain,
        body_html,
        owner_user.email,
        from_email=getattr(settings, "EMAIL_FROM_BILLING", None),
    )


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

    return _send_email_safe(
        subject,
        body_plain,
        body_html,
        owner_user.email,
        from_email=getattr(settings, "EMAIL_FROM_BILLING", None),
    )


_AUTO_RENEWAL_FAILURE_REASON_MESSAGES = {
    "no_owner": (
        "Não encontrámos um responsável (owner) ativo para a tua conta, por isso "
        "não conseguimos processar a compra automática."
    ),
    "no_payment_customer": (
        "Ainda não existe nenhum método de pagamento associado à tua conta no "
        "Stripe."
    ),
    "no_payment_method": (
        "Não encontrámos um cartão predefinido guardado para cobrança automática."
    ),
    "invalid_price_id": (
        "O pacote de crédito configurado para renovação automática já não é " "válido."
    ),
    "charge_failed": ("A cobrança no teu cartão foi recusada pelo banco/emissor."),
}


def send_comm_auto_renewal_failed_email(
    tenant,
    owner_user,
    reason: str,
):
    """
    Avisa o owner que a renovação automática de crédito de comunicação falhou
    em duas tentativas consecutivas (BE-CREDITS-03 #507). Enviado só a partir
    da 2ª falha seguida, para evitar ruído em blips pontuais.
    """
    subject = "⚠️ Renovação automática de crédito falhou - TimelyOne"
    reason_message = _AUTO_RENEWAL_FAILURE_REASON_MESSAGES.get(
        reason, "Não foi possível concluir a compra automática de crédito."
    )

    body_plain = f"""
Olá {owner_user.first_name or owner_user.username},

A renovação automática de crédito de comunicação da tua conta "{tenant.name}" falhou em mais de uma tentativa seguida.

Motivo: {reason_message}

Enquanto isto não for resolvido, o envio de mensagens (SMS/WhatsApp) pode ficar bloqueado quando o saldo de crédito acabar.

Para resolver, acede às configurações de pagamentos e confirma o método de pagamento e o pacote de renovação automática.

Equipe TimelyOne
"""

    body_html = f"""
        <div style="font-family: Arial, sans-serif; font-size: 14px; color: #222; max-width: 600px; margin: 0 auto;">
          <div style="background-color: #fff3cd; border-left: 4px solid #ffc107; padding: 15px; margin-bottom: 20px;">
            <h2 style="color: #856404; margin-top: 0;">⚠️ Renovação automática de crédito falhou</h2>
          </div>

          <p>Olá <strong>{owner_user.first_name or owner_user.username}</strong>,</p>

          <p>A renovação automática de crédito de comunicação da tua conta "<strong>{tenant.name}</strong>" falhou em mais de uma tentativa seguida.</p>

          <div style="background-color: #f8d7da; padding: 15px; border-left: 4px solid #d9534f; margin: 20px 0;">
            <p style="margin: 0; color: #721c24;"><strong>Motivo:</strong> {reason_message}</p>
          </div>

          <p>Enquanto isto não for resolvido, o envio de mensagens (SMS/WhatsApp) pode ficar bloqueado quando o saldo de crédito acabar.</p>

          <p>Para resolver, acede às configurações de pagamentos e confirma o método de pagamento e o pacote de renovação automática.</p>

          <p style="margin-top: 20px;">
            <strong>Equipe TimelyOne</strong>
          </p>
        </div>
    """

    return _send_email_safe(
        subject,
        body_plain,
        body_html,
        owner_user.email,
        from_email=getattr(settings, "EMAIL_FROM_BILLING", None),
    )
