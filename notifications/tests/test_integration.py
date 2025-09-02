import pytest
from django.contrib.auth import get_user_model
from django.test import override_settings
from users.models import Tenant
from core.models import Appointment, Service, Professional, ScheduleSlot
from notifications.models import Notification, NotificationLog
from notifications.signals import send_appointment_notifications

User = get_user_model()


@pytest.mark.django_db
class TestNotificationIntegration:
    """Testes para integração de notificações com agendamentos"""

    def test_appointment_creation_sends_notification(
        self, tenant_fixture, user_fixture
    ):
        """Teste que criação de agendamento envia notificação"""
        # Criar dependências
        service = Service.objects.create(
            tenant=tenant_fixture,
            user=user_fixture,
            name="Corte de Cabelo",
            duration_minutes=60,
            price_eur=25.0,
        )

        professional = Professional.objects.create(
            tenant=tenant_fixture,
            user=user_fixture,
            name="João Silva",
            bio="Especialista em cortes masculinos",
        )

        from datetime import datetime, timedelta
        from django.utils import timezone

        slot = ScheduleSlot.objects.create(
            tenant=tenant_fixture,
            professional=professional,
            start_time=timezone.now() + timedelta(days=1),
            end_time=timezone.now() + timedelta(days=1, hours=1),
            is_available=False,
        )

        # Criar agendamento (deve disparar signal)
        appointment = Appointment.objects.create(
            tenant=tenant_fixture,
            client=user_fixture,
            service=service,
            professional=professional,
            slot=slot,
            status="scheduled",
        )

        # Verificar que notificação in-app foi criada
        notification = Notification.objects.filter(
            tenant=tenant_fixture,
            user=user_fixture,
            notification_type="appointment_created",
        ).first()

        assert notification is not None
        assert "Novo Agendamento Confirmado" in notification.title
        assert "Corte de Cabelo" in notification.message
        assert notification.metadata["appointment_id"] == appointment.id
        assert notification.metadata["service_name"] == "Corte de Cabelo"

        # Verificar que logs foram criados (in_app, push_web, push_mobile)
        logs = NotificationLog.objects.filter(
            tenant=tenant_fixture,
            user=user_fixture,
            notification_type="appointment_created",
        )

        # Deve ter pelo menos o log in_app
        assert logs.filter(channel="in_app", status="sent").exists()

        # Push logs podem falhar se não há device registrado
        assert logs.filter(channel="push_web").exists()
        assert logs.filter(channel="push_mobile").exists()

    def test_appointment_cancellation_sends_notification(
        self, tenant_fixture, user_fixture
    ):
        """Teste que cancelamento de agendamento envia notificação"""
        # Criar agendamento
        service = Service.objects.create(
            tenant=tenant_fixture,
            user=user_fixture,
            name="Manicure",
            duration_minutes=45,
            price_eur=15.0,
        )

        professional = Professional.objects.create(
            tenant=tenant_fixture,
            user=user_fixture,
            name="Maria Santos",
            bio="Especialista em manicure e pedicure",
        )

        from datetime import datetime, timedelta
        from django.utils import timezone

        slot = ScheduleSlot.objects.create(
            tenant=tenant_fixture,
            professional=professional,
            start_time=timezone.now() + timedelta(days=1),
            end_time=timezone.now() + timedelta(days=1, minutes=45),
            is_available=False,
        )

        appointment = Appointment.objects.create(
            tenant=tenant_fixture,
            client=user_fixture,
            service=service,
            professional=professional,
            slot=slot,
            status="scheduled",
        )

        # Limpar notificações da criação
        Notification.objects.filter(tenant=tenant_fixture, user=user_fixture).delete()

        NotificationLog.objects.filter(
            tenant=tenant_fixture, user=user_fixture
        ).delete()

        # Cancelar agendamento
        appointment.status = "cancelled"
        appointment.save()

        # Verificar notificação de cancelamento
        notification = Notification.objects.filter(
            tenant=tenant_fixture,
            user=user_fixture,
            notification_type="appointment_cancelled",
        ).first()

        assert notification is not None
        assert "Agendamento Cancelado" in notification.title
        assert "Manicure" in notification.message
        assert notification.metadata["appointment_id"] == appointment.id
        assert notification.metadata["status"] == "cancelled"

        # Verificar que notificação de cancelamento inclui SMS
        logs = NotificationLog.objects.filter(
            tenant=tenant_fixture,
            user=user_fixture,
            notification_type="appointment_cancelled",
        )

        assert logs.filter(channel="in_app", status="sent").exists()
        assert logs.filter(channel="sms").exists()  # Pode falhar se não há telefone

    def test_appointment_completion_sends_notification(
        self, tenant_fixture, user_fixture
    ):
        """Teste que conclusão de agendamento envia notificação"""
        # Criar agendamento
        service = Service.objects.create(
            tenant=tenant_fixture,
            user=user_fixture,
            name="Massagem",
            duration_minutes=90,
            price_eur=50.0,
        )

        professional = Professional.objects.create(
            tenant=tenant_fixture,
            user=user_fixture,
            name="Ana Costa",
            bio="Especialista em massagens relaxantes",
        )

        from datetime import datetime, timedelta
        from django.utils import timezone

        slot = ScheduleSlot.objects.create(
            tenant=tenant_fixture,
            professional=professional,
            start_time=timezone.now() - timedelta(hours=2),  # No passado
            end_time=timezone.now() - timedelta(minutes=30),
            is_available=False,
        )

        appointment = Appointment.objects.create(
            tenant=tenant_fixture,
            client=user_fixture,
            service=service,
            professional=professional,
            slot=slot,
            status="scheduled",
        )

        # Limpar notificações da criação
        Notification.objects.filter(tenant=tenant_fixture, user=user_fixture).delete()

        # Marcar como concluído
        appointment.status = "completed"
        appointment.save()

        # Verificar notificação de conclusão
        notification = Notification.objects.filter(
            tenant=tenant_fixture,
            user=user_fixture,
            notification_type="appointment_completed",
        ).first()

        assert notification is not None
        assert "Serviço Concluído" in notification.title
        assert "Massagem" in notification.message
        assert notification.metadata["status"] == "completed"

    def test_payment_confirmation_sends_notification(
        self, tenant_fixture, user_fixture
    ):
        """Teste que confirmação de pagamento envia notificação"""
        # Criar agendamento concluído
        service = Service.objects.create(
            tenant=tenant_fixture,
            user=user_fixture,
            name="Pedicure",
            duration_minutes=60,
            price_eur=20.0,
        )

        professional = Professional.objects.create(
            tenant=tenant_fixture,
            user=user_fixture,
            name="Sofia Oliveira",
            bio="Especialista em pedicure e cuidados dos pés",
        )

        from datetime import datetime, timedelta
        from django.utils import timezone

        slot = ScheduleSlot.objects.create(
            tenant=tenant_fixture,
            professional=professional,
            start_time=timezone.now() - timedelta(hours=1),
            end_time=timezone.now(),
            is_available=False,
        )

        appointment = Appointment.objects.create(
            tenant=tenant_fixture,
            client=user_fixture,
            service=service,
            professional=professional,
            slot=slot,
            status="completed",
        )

        # Limpar notificações anteriores
        Notification.objects.filter(tenant=tenant_fixture, user=user_fixture).delete()

        # Marcar pagamento como confirmado
        appointment.status = "paid"
        appointment.save()

        # Verificar notificação de pagamento
        notification = Notification.objects.filter(
            tenant=tenant_fixture,
            user=user_fixture,
            notification_type="payment_received",
        ).first()

        assert notification is not None
        assert "Pagamento Confirmado" in notification.title
        assert "Pedicure" in notification.message
        assert notification.metadata["status"] == "paid"

    def test_no_notification_for_unchanged_appointment(
        self, tenant_fixture, user_fixture
    ):
        """Teste que não envia notificação para agendamentos sem mudanças relevantes"""
        # Criar agendamento
        service = Service.objects.create(
            tenant=tenant_fixture,
            user=user_fixture,
            name="Teste",
            duration_minutes=30,
            price_eur=10.0,
        )

        professional = Professional.objects.create(
            tenant=tenant_fixture,
            user=user_fixture,
            name="Teste",
            bio="Profissional de teste",
        )

        from datetime import datetime, timedelta
        from django.utils import timezone

        slot = ScheduleSlot.objects.create(
            tenant=tenant_fixture,
            professional=professional,
            start_time=timezone.now() + timedelta(days=1),
            end_time=timezone.now() + timedelta(days=1, minutes=30),
            is_available=False,
        )

        appointment = Appointment.objects.create(
            tenant=tenant_fixture,
            client=user_fixture,
            service=service,
            professional=professional,
            slot=slot,
            status="scheduled",
        )

        # Limpar notificações da criação
        Notification.objects.filter(tenant=tenant_fixture, user=user_fixture).delete()

        # Salvar sem mudanças relevantes (mesmo status)
        appointment.save()

        # Não deve ter criado novas notificações
        new_notifications = Notification.objects.filter(
            tenant=tenant_fixture, user=user_fixture
        ).count()

        assert new_notifications == 0
