from django.test import TestCase, override_settings
from django.core import mail
from django.contrib.auth import get_user_model
from django.utils import timezone
from datetime import timedelta
from core.models import Appointment, Service, Professional, ScheduleSlot
from users.models import Tenant
from notifications.services import notification_service

User = get_user_model()


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class EmailNotificationTest(TestCase):
    def setUp(self):
        # Configurar tenant
        self.tenant = Tenant.objects.create(
            name="Salão Teste",
            slug="salao-teste",
            sms_enabled=True,
        )

        # Configurar cliente
        self.client_user = User.objects.create_user(
            username="cliente_teste",
            email="cliente@example.com",
            password="password123",
            tenant=self.tenant,
        )

        # Configurar profissional
        self.pro_user = User.objects.create_user(
            username="pro_teste",
            email="pro@example.com",
            password="password123",
            tenant=self.tenant,
        )
        self.professional = Professional.objects.create(
            tenant=self.tenant,
            user=self.pro_user,
            name="João Cabeleireiro",
        )

        # Configurar serviço
        self.service = Service.objects.create(
            tenant=self.tenant,
            user=self.pro_user,
            name="Corte Masculino",
            duration_minutes=30,
            price_eur=15.00,
        )

        # Configurar slot
        self.slot = ScheduleSlot.objects.create(
            tenant=self.tenant,
            professional=self.professional,
            start_time=timezone.now() + timedelta(days=1),
            end_time=timezone.now() + timedelta(days=1, minutes=30),
        )

    def test_appointment_cancellation_sends_email(self):
        """Teste se o cancelamento de agendamento envia e-mail"""
        # Criar agendamento
        appointment = Appointment.objects.create(
            tenant=self.tenant,
            client=self.client_user,
            service=self.service,
            professional=self.professional,
            slot=self.slot,
            status="scheduled",
        )

        # Limpar outbox (pode ter e-mails de criação se houver lógica para isso)
        mail.outbox = []

        # Cancelar agendamento
        appointment.status = "cancelled"
        appointment.save()

        # Verificar envio de e-mail
        self.assertEqual(len(mail.outbox), 1)
        email = mail.outbox[0]

        # Verificar destinatário e assunto
        self.assertEqual(email.to, ["cliente@example.com"])
        self.assertIn("Agendamento Cancelado", email.subject)
        self.assertIn("Corte Masculino", email.body)
        self.assertIn("cancelado", email.body)

    def test_email_driver_direct_send(self):
        """Teste direto do EmailDriver via notification_service"""
        success = notification_service.send_notification(
            tenant=self.tenant,
            user=self.client_user,
            channels=["email"],
            notification_type="system",
            title="Teste Direto",
            message="Mensagem de teste",
        )

        self.assertTrue(success["email"])
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].subject, "Teste Direto")

    def test_email_send_fails_without_email(self):
        """Teste falha quando usuário não tem e-mail"""
        user_no_email = User.objects.create_user(
            username="no_email",
            email="temp@example.com",
            tenant=self.tenant,
        )
        # Remover email diretamente via update
        User.objects.filter(pk=user_no_email.pk).update(email="")
        user_no_email.refresh_from_db()

        success = notification_service.send_notification(
            tenant=self.tenant,
            user=user_no_email,
            channels=["email"],
            notification_type="system",
            title="Teste Falha",
            message="Não deve enviar",
        )

        self.assertFalse(success["email"])
        self.assertEqual(len(mail.outbox), 0)
