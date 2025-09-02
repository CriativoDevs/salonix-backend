import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from users.models import Tenant
from notifications.models import Notification, NotificationDevice, NotificationLog

User = get_user_model()


@pytest.mark.django_db
class TestNotificationModels:
    """Testes para os modelos de notificação"""

    def test_notification_device_creation(self, tenant_fixture, user_fixture):
        """Teste criação de NotificationDevice"""
        device = NotificationDevice.objects.create(
            tenant=tenant_fixture,
            user=user_fixture,
            device_type="web",
            token="test-web-token-123",
        )

        assert device.tenant == tenant_fixture
        assert device.user == user_fixture
        assert device.device_type == "web"
        assert device.token == "test-web-token-123"
        assert device.is_active is True
        assert (
            str(device) == f"{user_fixture.username} - Web Push ({tenant_fixture.name})"
        )

    def test_notification_device_unique_constraint(self, tenant_fixture, user_fixture):
        """Teste constraint único para user + device_type + token"""
        # Criar primeiro device
        NotificationDevice.objects.create(
            tenant=tenant_fixture,
            user=user_fixture,
            device_type="web",
            token="duplicate-token",
        )

        # Tentar criar device duplicado deve falhar
        with pytest.raises(Exception):  # IntegrityError
            NotificationDevice.objects.create(
                tenant=tenant_fixture,
                user=user_fixture,
                device_type="web",
                token="duplicate-token",
            )

    def test_notification_creation(self, tenant_fixture, user_fixture):
        """Teste criação de Notification"""
        notification = Notification.objects.create(
            tenant=tenant_fixture,
            user=user_fixture,
            notification_type="appointment_created",
            title="Novo Agendamento",
            message="Você tem um novo agendamento para amanhã",
            metadata={"appointment_id": 123},
        )

        assert notification.tenant == tenant_fixture
        assert notification.user == user_fixture
        assert notification.notification_type == "appointment_created"
        assert notification.title == "Novo Agendamento"
        assert notification.is_read is False
        assert notification.read_at is None
        assert notification.metadata == {"appointment_id": 123}
        assert "● Novo Agendamento" in str(notification)

    def test_notification_mark_as_read(self, tenant_fixture, user_fixture):
        """Teste marcar notificação como lida"""
        notification = Notification.objects.create(
            tenant=tenant_fixture,
            user=user_fixture,
            notification_type="system",
            title="Teste",
            message="Teste",
        )

        # Inicialmente não lida
        assert notification.is_read is False
        assert notification.read_at is None

        # Marcar como lida
        from django.utils import timezone

        read_time = timezone.now()
        notification.is_read = True
        notification.read_at = read_time
        notification.save()

        # Verificar que foi marcada
        notification.refresh_from_db()
        assert notification.is_read is True
        assert notification.read_at == read_time
        assert "✓ Teste" in str(notification)

    def test_notification_log_creation(self, tenant_fixture, user_fixture):
        """Teste criação de NotificationLog"""
        log = NotificationLog.objects.create(
            tenant=tenant_fixture,
            user=user_fixture,
            channel="push_web",
            notification_type="appointment_reminder",
            title="Lembrete",
            message="Você tem um agendamento em 1 hora",
            status="sent",
            metadata={"device_token": "abc123"},
        )

        assert log.tenant == tenant_fixture
        assert log.user == user_fixture
        assert log.channel == "push_web"
        assert log.status == "sent"
        assert log.metadata == {"device_token": "abc123"}
        assert "Web Push - sent" in str(log)

    def test_notification_log_with_error(self, tenant_fixture, user_fixture):
        """Teste NotificationLog com erro"""
        log = NotificationLog.objects.create(
            tenant=tenant_fixture,
            user=user_fixture,
            channel="sms",
            notification_type="system",
            title="Teste",
            message="Teste SMS",
            status="failed",
            error_message="Número inválido",
        )

        assert log.status == "failed"
        assert log.error_message == "Número inválido"
        assert log.sent_at is None
        assert log.delivered_at is None
