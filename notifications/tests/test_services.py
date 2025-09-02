import pytest
from unittest.mock import patch, MagicMock
from django.contrib.auth import get_user_model
from users.models import Tenant
from notifications.models import Notification, NotificationDevice, NotificationLog
from notifications.services import (
    NotificationService,
    InAppNotificationDriver,
    WebPushDriver,
    MobilePushDriver,
    SMSDriver,
    WhatsAppDriver,
    notification_service,
)

User = get_user_model()


@pytest.mark.django_db
class TestNotificationService:
    """Testes para o serviço de notificações"""

    def test_send_in_app_notification(self, tenant_fixture, user_fixture):
        """Teste envio de notificação in-app"""
        results = notification_service.send_notification(
            tenant=tenant_fixture,
            user=user_fixture,
            channels=["in_app"],
            notification_type="appointment_created",
            title="Novo Agendamento",
            message="Você tem um agendamento para amanhã",
            metadata={"appointment_id": 123},
        )

        # Verificar resultado
        assert results["in_app"] is True

        # Verificar que notificação foi criada
        notification = Notification.objects.get(
            tenant=tenant_fixture,
            user=user_fixture,
            notification_type="appointment_created",
        )
        assert notification.title == "Novo Agendamento"
        assert notification.message == "Você tem um agendamento para amanhã"
        assert notification.metadata == {"appointment_id": 123}

        # Verificar que log foi criado
        log = NotificationLog.objects.get(
            tenant=tenant_fixture, user=user_fixture, channel="in_app"
        )
        assert log.status == "sent"

    def test_send_multiple_channels(self, tenant_fixture, user_fixture):
        """Teste envio por múltiplos canais"""
        results = notification_service.send_notification(
            tenant=tenant_fixture,
            user=user_fixture,
            channels=["in_app", "push_web", "sms"],
            notification_type="system",
            title="Teste Multi-Canal",
            message="Mensagem de teste",
        )

        # in_app deve funcionar sempre
        assert results["in_app"] is True

        # push_web deve falhar (sem device registrado)
        assert results["push_web"] is False

        # sms deve falhar (sem telefone)
        assert results["sms"] is False

        # Verificar logs criados
        logs = NotificationLog.objects.filter(tenant=tenant_fixture, user=user_fixture)
        assert logs.count() == 3

        # Verificar status dos logs
        in_app_log = logs.get(channel="in_app")
        assert in_app_log.status == "sent"

        push_log = logs.get(channel="push_web")
        assert push_log.status == "failed"

        sms_log = logs.get(channel="sms")
        assert sms_log.status == "failed"

    def test_test_channel_functionality(self, tenant_fixture, user_fixture):
        """Teste funcionalidade de teste de canal"""
        result = notification_service.test_channel(
            tenant=tenant_fixture,
            user=user_fixture,
            channel="in_app",
            message="Mensagem de teste",
        )

        assert result is True

        # Verificar que notificação de teste foi criada
        notification = Notification.objects.get(
            tenant=tenant_fixture, user=user_fixture, notification_type="system"
        )
        assert notification.title == "Teste de Notificação"
        assert notification.message == "Mensagem de teste"
        assert notification.metadata["is_test"] is True

    def test_unknown_channel(self, tenant_fixture, user_fixture):
        """Teste canal desconhecido"""
        results = notification_service.send_notification(
            tenant=tenant_fixture,
            user=user_fixture,
            channels=["unknown_channel"],
            notification_type="system",
            title="Teste",
            message="Teste",
        )

        assert results["unknown_channel"] is False


@pytest.mark.django_db
class TestNotificationDrivers:
    """Testes para os drivers específicos"""

    def test_in_app_driver(self, tenant_fixture, user_fixture):
        """Teste driver in-app"""
        driver = InAppNotificationDriver()

        result = driver.send(
            tenant=tenant_fixture,
            user=user_fixture,
            notification_type="test",
            title="Teste Driver",
            message="Mensagem teste",
            metadata={"test": True},
        )

        assert result is True

        # Verificar notificação criada
        notification = Notification.objects.get(
            tenant=tenant_fixture, user=user_fixture
        )
        assert notification.title == "Teste Driver"
        assert notification.metadata == {"test": True}

    def test_web_push_driver_no_device(self, tenant_fixture, user_fixture):
        """Teste driver web push sem device registrado"""
        driver = WebPushDriver()

        result = driver.send(
            tenant=tenant_fixture,
            user=user_fixture,
            notification_type="test",
            title="Teste",
            message="Teste",
            metadata={},
        )

        # Deve falhar pois não há device registrado
        assert result is False

    def test_web_push_driver_with_device(self, tenant_fixture, user_fixture):
        """Teste driver web push com device registrado"""
        # Criar device web
        NotificationDevice.objects.create(
            tenant=tenant_fixture,
            user=user_fixture,
            device_type="web",
            token="test-web-token",
        )

        driver = WebPushDriver()

        result = driver.send(
            tenant=tenant_fixture,
            user=user_fixture,
            notification_type="test",
            title="Teste",
            message="Teste",
            metadata={},
        )

        # Deve simular sucesso
        assert result is True

    def test_mobile_push_driver_with_device(self, tenant_fixture, user_fixture):
        """Teste driver mobile push com device registrado"""
        # Criar device mobile
        NotificationDevice.objects.create(
            tenant=tenant_fixture,
            user=user_fixture,
            device_type="mobile",
            token="ExponentPushToken[abc123]",
        )

        driver = MobilePushDriver()

        result = driver.send(
            tenant=tenant_fixture,
            user=user_fixture,
            notification_type="test",
            title="Teste",
            message="Teste",
            metadata={},
        )

        # Deve simular sucesso
        assert result is True

    def test_sms_driver_no_phone(self, tenant_fixture, user_fixture):
        """Teste driver SMS sem telefone"""
        driver = SMSDriver()

        result = driver.send(
            tenant=tenant_fixture,
            user=user_fixture,
            notification_type="test",
            title="Teste",
            message="Teste",
            metadata={},
        )

        # Deve falhar pois não há telefone
        assert result is False

    def test_sms_driver_with_phone(self, tenant_fixture, user_fixture):
        """Teste driver SMS com telefone"""
        # Adicionar telefone ao usuário
        user_fixture.phone_number = "+351912345678"
        user_fixture.save()

        driver = SMSDriver()

        result = driver.send(
            tenant=tenant_fixture,
            user=user_fixture,
            notification_type="test",
            title="Teste",
            message="Teste SMS",
            metadata={},
        )

        # Deve simular sucesso
        assert result is True

    def test_whatsapp_driver_with_phone(self, tenant_fixture, user_fixture):
        """Teste driver WhatsApp com telefone"""
        # Adicionar telefone ao usuário
        user_fixture.phone_number = "+351912345678"
        user_fixture.save()

        driver = WhatsAppDriver()

        result = driver.send(
            tenant=tenant_fixture,
            user=user_fixture,
            notification_type="test",
            title="Teste WhatsApp",
            message="Mensagem WhatsApp",
            metadata={},
        )

        # Deve simular sucesso
        assert result is True
