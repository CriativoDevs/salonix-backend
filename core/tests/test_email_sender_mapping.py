"""
BE-MARKETING-02 (#477): mapeamento de remetente (from_email) por tipo de email.

Mapeamento autoritativo (definido pelo dono do produto):
- booking@timelyone.today      -> confirmacao/alteracao de agendamento
- cancellation@timelyone.today -> cancelamento de agendamento
- support@timelyone.today      -> suporte, feedback da plataforma e demais
                                   notificacoes transacionais nao cobertas acima
- billing@timelyone.today      -> faturacao/subscricao (Stripe) e ciclo de vida
                                   da conta (cancelamento/reativacao, credito)
- timelyone@timelyone.today    -> NUNCA remetente automatico (contacto geral)
"""

from datetime import date, timedelta
from unittest.mock import MagicMock, patch

import pytest
from django.core import mail
from django.test.utils import override_settings

from core import email_utils
from notifications.services import EmailDriver, send_feedback_digest_email_if_due
from users.models import CustomUser, Tenant, TenantStaffMember

pytestmark = pytest.mark.django_db


def _capture_send_email_safe():
    calls = []

    def fake(subject, body_plain, body_html, to_emails, reply_to=None, from_email=None):
        calls.append({"subject": subject, "to": to_emails, "from_email": from_email})
        return True

    return calls, fake


# --- Settings expõem os 4 remetentes com defaults sensatos --------------------


def test_settings_expose_email_from_mapping(settings):
    assert settings.EMAIL_FROM_BOOKING == "TimelyOne <booking@timelyone.today>"
    assert (
        settings.EMAIL_FROM_CANCELLATION == "TimelyOne <cancellation@timelyone.today>"
    )
    assert settings.EMAIL_FROM_SUPPORT == "TimelyOne <support@timelyone.today>"
    assert settings.EMAIL_FROM_BILLING == "TimelyOne <billing@timelyone.today>"


# --- core/email_utils.py: cada função usa o remetente correto -----------------


def test_appointment_confirmation_uses_booking_sender():
    calls, fake = _capture_send_email_safe()
    with patch("core.email_utils._send_email_safe", side_effect=fake):
        from django.utils import timezone

        email_utils.send_appointment_confirmation_email(
            "cliente@example.com", "Cliente", "Corte", timezone.now()
        )
    assert calls[0]["from_email"] == "TimelyOne <booking@timelyone.today>"


def test_bulk_appointment_confirmation_uses_booking_sender():
    calls, fake = _capture_send_email_safe()
    with patch("core.email_utils._send_email_safe", side_effect=fake):
        from django.utils import timezone

        email_utils.send_bulk_appointment_confirmation_email(
            "cliente@example.com",
            "Cliente",
            [{"service_name": "Corte", "start_time": timezone.now()}],
        )
    assert calls[0]["from_email"] == "TimelyOne <booking@timelyone.today>"


def test_appointment_cancellation_uses_cancellation_sender():
    calls, fake = _capture_send_email_safe()
    with patch("core.email_utils._send_email_safe", side_effect=fake):
        from django.utils import timezone

        email_utils.send_appointment_cancellation_email(
            "cliente@example.com",
            "salao@example.com",
            "Cliente",
            "Corte",
            timezone.now(),
        )
    assert calls[0]["from_email"] == "TimelyOne <cancellation@timelyone.today>"


@pytest.mark.parametrize(
    "fn,args,kwargs",
    [
        (
            "send_staff_access_link_email",
            ("colab@example.com", "https://x/access", "Salao"),
            {},
        ),
        (
            "send_marketing_email",
            ("cliente@example.com", "Cliente", "Assunto", "corpo"),
            {"tenant_id": 1, "customer_id": 1},
        ),
        (
            "send_staff_invite_email",
            ("colab@example.com", "https://x/accept", "Salao"),
            {},
        ),
        (
            "send_tenant_welcome_email",
            ("owner@example.com",),
            {"owner_name": "Owner", "salon_name": "Salao"},
        ),
        (
            "send_voucher_email",
            ("cliente@example.com", "Cliente", "CODE10", "percent"),
            {"voucher_value": 10},
        ),
    ],
)
def test_support_bucket_senders_use_support_sender(fn, args, kwargs):
    calls, fake = _capture_send_email_safe()
    with patch("core.email_utils._send_email_safe", side_effect=fake):
        getattr(email_utils, fn)(*args, **kwargs)
    assert calls[0]["from_email"] == "TimelyOne <support@timelyone.today>"


def test_account_cancellation_uses_billing_sender():
    from django.utils import timezone

    tenant = Tenant.objects.create(name="Salao Teste", slug="salao-teste-cancel")
    tenant.cancelled_at = timezone.now()
    tenant.scheduled_deletion_at = date.today() + timedelta(days=30)
    owner = CustomUser.objects.create_user(
        username="owner_cancel",
        email="owner_cancel@example.com",
        password="pass12345",
        first_name="Owner",
        tenant=tenant,
    )
    calls, fake = _capture_send_email_safe()
    with patch("core.email_utils._send_email_safe", side_effect=fake):
        email_utils.send_account_cancellation_email(
            tenant, owner, "https://x/reactivate"
        )
    assert calls[0]["from_email"] == "TimelyOne <billing@timelyone.today>"


def test_deletion_reminder_uses_billing_sender():
    tenant = Tenant.objects.create(name="Salao Teste", slug="salao-teste-remind")
    tenant.scheduled_deletion_at = date.today() + timedelta(days=7)
    owner = CustomUser.objects.create_user(
        username="owner_remind",
        email="owner_remind@example.com",
        password="pass12345",
        tenant=tenant,
    )
    calls, fake = _capture_send_email_safe()
    with patch("core.email_utils._send_email_safe", side_effect=fake):
        email_utils.send_deletion_reminder_email(tenant, owner, "https://x/reactivate")
    assert calls[0]["from_email"] == "TimelyOne <billing@timelyone.today>"


def test_account_reactivation_uses_billing_sender():
    tenant = Tenant.objects.create(name="Salao Teste", slug="salao-teste-react")
    owner = CustomUser.objects.create_user(
        username="owner_react",
        email="owner_react@example.com",
        password="pass12345",
        tenant=tenant,
    )
    calls, fake = _capture_send_email_safe()
    with patch("core.email_utils._send_email_safe", side_effect=fake):
        email_utils.send_account_reactivation_email(tenant, owner)
    assert calls[0]["from_email"] == "TimelyOne <billing@timelyone.today>"


def test_comm_auto_renewal_failed_uses_billing_sender():
    tenant = Tenant.objects.create(name="Salao Teste", slug="salao-teste-renewal")
    owner = CustomUser.objects.create_user(
        username="owner_renewal",
        email="owner_renewal@example.com",
        password="pass12345",
        tenant=tenant,
    )
    calls, fake = _capture_send_email_safe()
    with patch("core.email_utils._send_email_safe", side_effect=fake):
        email_utils.send_comm_auto_renewal_failed_email(tenant, owner, "charge_failed")
    assert calls[0]["from_email"] == "TimelyOne <billing@timelyone.today>"


# --- notifications/services.py: EmailDriver e feedback digest -----------------


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
def test_email_driver_uses_cancellation_sender_for_cancellation_type():
    tenant = Tenant.objects.create(name="Salao Teste", slug="salao-teste-driver")
    user = CustomUser.objects.create_user(
        username="cliente_driver",
        email="cliente_driver@example.com",
        password="pass12345",
        tenant=tenant,
    )
    mail.outbox = []
    EmailDriver().send(
        tenant=tenant,
        user=user,
        notification_type="appointment_cancelled",
        title="Agendamento Cancelado",
        message="Seu agendamento foi cancelado",
        metadata={},
    )
    assert len(mail.outbox) == 1
    assert mail.outbox[0].from_email == "TimelyOne <cancellation@timelyone.today>"


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
def test_email_driver_uses_booking_sender_for_appointment_types():
    tenant = Tenant.objects.create(name="Salao Teste", slug="salao-teste-driver2")
    user = CustomUser.objects.create_user(
        username="cliente_driver2",
        email="cliente_driver2@example.com",
        password="pass12345",
        tenant=tenant,
    )
    mail.outbox = []
    EmailDriver().send(
        tenant=tenant,
        user=user,
        notification_type="appointment_created",
        title="Novo Agendamento",
        message="Seu agendamento foi confirmado",
        metadata={},
    )
    assert mail.outbox[0].from_email == "TimelyOne <booking@timelyone.today>"


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
def test_email_driver_uses_support_sender_for_unmapped_type():
    tenant = Tenant.objects.create(name="Salao Teste", slug="salao-teste-driver3")
    user = CustomUser.objects.create_user(
        username="cliente_driver3",
        email="cliente_driver3@example.com",
        password="pass12345",
        tenant=tenant,
    )
    mail.outbox = []
    EmailDriver().send(
        tenant=tenant,
        user=user,
        notification_type="system",
        title="Teste",
        message="Mensagem de teste",
        metadata={},
    )
    assert mail.outbox[0].from_email == "TimelyOne <support@timelyone.today>"


def test_feedback_digest_uses_support_sender(monkeypatch):
    from django.utils import timezone

    tenant = Tenant.objects.create(
        name="Salao Teste",
        slug="salao-teste-digest",
        contact_email="dono@example.com",
        feedback_digest_enabled=True,
        feedback_digest_frequency="daily",
        feedback_digest_time=timezone.now().time(),
    )
    from core.models import Feedback

    Feedback.objects.create(
        tenant=tenant, category="general", rating=5, message="Otimo!"
    )
    captured = {}
    with patch("notifications.services.EmailMultiAlternatives") as mock_cls:
        instance = MagicMock()
        mock_cls.return_value = instance

        def _capture(subject, body, from_email, to):
            captured["from_email"] = from_email
            return instance

        mock_cls.side_effect = _capture
        send_feedback_digest_email_if_due(tenant)
    assert captured["from_email"] == "TimelyOne <support@timelyone.today>"


# --- users/views.py: emails de acesso/reset de password (fallback support) ----


def test_staff_access_link_view_uses_support_sender(monkeypatch):
    from django.urls import reverse
    from rest_framework.test import APIClient

    tenant = Tenant.objects.create(name="Salao Teste", slug="salao-teste-access")
    owner = CustomUser.objects.create_user(
        username="owner_access",
        email="owner_access@example.com",
        password="pass12345",
        tenant=tenant,
    )
    TenantStaffMember.objects.create(
        tenant=tenant,
        user=owner,
        role=TenantStaffMember.Role.OWNER,
        status=TenantStaffMember.Status.ACTIVE,
    )
    staff_user = CustomUser.objects.create_user(
        username="staffie",
        email="staffie@example.com",
        password="pass12345",
        tenant=tenant,
    )
    staff_member = TenantStaffMember.objects.create(
        tenant=tenant,
        user=staff_user,
        role=TenantStaffMember.Role.COLLABORATOR,
        status=TenantStaffMember.Status.ACTIVE,
    )

    # send_staff_access_link_email é assíncrono (thread) e já coberto por outro
    # teste; aqui o foco é o segundo envio síncrono feito diretamente na view.
    monkeypatch.setattr(
        "core.email_utils.send_staff_access_link_email",
        lambda to_email, access_url, salon_name: True,
        raising=True,
    )

    client = APIClient()
    client.force_authenticate(user=owner)

    with override_settings(
        EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend"
    ):
        mail.outbox = []
        url = reverse("tenant_staff_access_link")
        resp = client.post(url, {"id": staff_member.id}, format="json")
        assert resp.status_code == 200, resp.content
        assert len(mail.outbox) == 1
        assert mail.outbox[0].from_email == "TimelyOne <support@timelyone.today>"


# --- Nunca timelyone@timelyone.today como remetente automático ----------------


ALL_EMAIL_UTILS_SENDERS = [
    "send_appointment_confirmation_email",
    "send_appointment_cancellation_email",
    "send_staff_access_link_email",
    "send_bulk_appointment_confirmation_email",
    "send_marketing_email",
    "send_staff_invite_email",
    "send_tenant_welcome_email",
    "send_voucher_email",
]


@pytest.mark.parametrize("fn_name", ALL_EMAIL_UTILS_SENDERS)
def test_no_automatic_email_uses_general_contact_address(fn_name):
    """timelyone@timelyone.today é reservado ao contacto geral (landing), nunca
    remetente de email automático."""
    from django.utils import timezone

    calls, fake = _capture_send_email_safe()
    fn = getattr(email_utils, fn_name)
    with patch("core.email_utils._send_email_safe", side_effect=fake):
        if fn_name == "send_appointment_confirmation_email":
            fn("cliente@example.com", "Cliente", "Corte", timezone.now())
        elif fn_name == "send_appointment_cancellation_email":
            fn(
                "cliente@example.com",
                "salao@example.com",
                "Cliente",
                "Corte",
                timezone.now(),
            )
        elif fn_name == "send_staff_access_link_email":
            fn("colab@example.com", "https://x/access", "Salao")
        elif fn_name == "send_bulk_appointment_confirmation_email":
            fn(
                "cliente@example.com",
                "Cliente",
                [{"service_name": "Corte", "start_time": timezone.now()}],
            )
        elif fn_name == "send_marketing_email":
            fn(
                "cliente@example.com",
                "Cliente",
                "Assunto",
                "corpo",
                tenant_id=1,
                customer_id=1,
            )
        elif fn_name == "send_staff_invite_email":
            fn("colab@example.com", "https://x/accept", "Salao")
        elif fn_name == "send_tenant_welcome_email":
            fn("owner@example.com", owner_name="Owner", salon_name="Salao")
        elif fn_name == "send_voucher_email":
            fn(
                "cliente@example.com",
                "Cliente",
                "CODE10",
                "percent",
                voucher_value=10,
            )

    assert len(calls) == 1
    from_email = calls[0]["from_email"] or ""
    assert (
        "timelyone@timelyone.today" not in from_email
    ), f"{fn_name} usou o remetente de contacto geral: {from_email}"
