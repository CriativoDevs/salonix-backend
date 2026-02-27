import pytest
from decimal import Decimal
from unittest.mock import patch, Mock
from django.contrib.auth import get_user_model
from notifications.models import Notification, NotificationDevice, NotificationLog
from notifications.services import (
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

    def test_send_in_app_notification(
        self,
        tenant_fixture,
        user_fixture,
        service_fixture,
        professional_fixture,
        slot_fixture,
    ):
        """Teste envio de notificação in-app"""
        from core.models import Appointment

        appointment = Appointment.objects.create(
            tenant=tenant_fixture,
            client=user_fixture,
            service=service_fixture,
            professional=professional_fixture,
            slot=slot_fixture,
            status="scheduled",
        )

        results = notification_service.send_notification(
            tenant=tenant_fixture,
            user=user_fixture,
            channels=["in_app"],
            notification_type="appointment_created",
            title="Novo Agendamento",
            message="Você tem um agendamento para amanhã",
            metadata={"appointment_id": appointment.id},
        )

        # Verificar resultado
        assert results["in_app"] is True

        # Verificar que notificação foi criada
        notifications = Notification.objects.filter(
            tenant=tenant_fixture,
            user=user_fixture,
            notification_type="appointment_created",
        )
        # Pode haver mais de uma se o signal disparou na criação do appointment
        notification = notifications.filter(title="Novo Agendamento").first()
        assert notification is not None
        assert notification.message == "Você tem um agendamento para amanhã"
        assert notification.metadata["appointment_id"] == appointment.id

        # Verificar que log foi criado
        logs = NotificationLog.objects.filter(
            tenant=tenant_fixture, user=user_fixture, channel="in_app"
        )
        # Pode haver mais de um pelo signal
        log = logs.filter(title="Novo Agendamento").first()
        assert log is not None
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

    @patch("notifications.services.requests.post")
    def test_mobile_push_driver_with_device(
        self, mock_post, tenant_fixture, user_fixture
    ):
        """Teste driver mobile push com device registrado"""
        # Criar device mobile
        NotificationDevice.objects.create(
            tenant=tenant_fixture,
            user=user_fixture,
            device_type="mobile",
            token="ExponentPushToken[abc123]",
        )

        # Mock Expo response
        mock_response = Mock()
        mock_response.json.return_value = {"data": [{"status": "ok"}]}
        mock_response.raise_for_status = Mock()
        mock_post.return_value = mock_response

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

    @patch("notifications.services.sms_rate_limiter.check_and_increment")
    @patch("notifications.services.credit_service.charge_for_message")
    @patch("notifications.services.TwilioClient")
    def test_sms_driver_with_phone(
        self,
        mock_twilio,
        mock_charge,
        mock_rate,
        tenant_fixture,
        user_fixture,
        settings,
    ):
        """Teste driver SMS com telefone"""
        settings.SMS_ENABLED = True
        settings.TWILIO_ACCOUNT_SID = "test_sid"
        settings.TWILIO_AUTH_TOKEN = "test_token"
        settings.TWILIO_MESSAGING_SERVICE_SID = "mg_test"

        user_fixture.phone_number = "+351912345678"
        user_fixture.save()

        mock_rate.return_value = {"minute": 1}
        ledger = Mock(id=1)
        mock_charge.return_value = {
            "success": True,
            "cost": Decimal("0.09"),
            "new_balance": Decimal("1.00"),
            "ledger_entry": ledger,
        }

        twilio_message = Mock(sid="SM123", status="queued")
        mock_twilio.return_value.messages.create.return_value = twilio_message

        driver = SMSDriver()

        result = driver.send(
            tenant=tenant_fixture,
            user=user_fixture,
            notification_type="test",
            title="Teste",
            message="Teste SMS",
            metadata={},
        )

        assert result is True
        mock_twilio.return_value.messages.create.assert_called_once_with(
            body="Teste SMS",
            messaging_service_sid="mg_test",
            to="+351912345678",
        )

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
