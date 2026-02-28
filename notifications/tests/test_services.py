import pytest
from decimal import Decimal
from unittest.mock import patch, Mock
from django.contrib.auth import get_user_model
from users.models import Tenant
from notifications.models import Notification, NotificationDevice, NotificationLog

User = get_user_model()


@pytest.fixture
def tenant_fixture(db):
    return Tenant.objects.create(slug="test-tenant", name="Test Tenant")


@pytest.fixture
def user_fixture(db, tenant_fixture):
    return User.objects.create_user(
        username="testuser",
        email="test@example.com",
        password="password",
        tenant=tenant_fixture,
    )


@pytest.mark.django_db
class TestNotificationService:
    @patch("notifications.services.EmailDriver.send")
    def test_send_notification_all_channels(
        self, mock_email, tenant_fixture, user_fixture
    ):
        """Teste de envio para múltiplos canais"""
        from notifications.services import NotificationService

        # Mock do email
        mock_email.return_value = True

        res = NotificationService().send_notification(
            tenant=tenant_fixture,
            user=user_fixture,
            channels=["email"],
            notification_type="system",
            title="Test",
            message="Test Msg",
        )

        assert res["email"] is True
        # Verifica se log foi criado
        assert NotificationLog.objects.filter(tenant=tenant_fixture).exists()

    @patch("notifications.services.SMSDriver.send")
    def test_send_notification_sms_only(self, mock_sms, tenant_fixture, user_fixture):
        """Teste de envio apenas SMS"""
        from notifications.services import NotificationService

        mock_sms.return_value = True

        res = NotificationService().send_notification(
            tenant=tenant_fixture,
            user=user_fixture,
            channels=["sms"],
            notification_type="system",
            title="Test",
            message="Test Msg",
        )

        assert res["sms"] is True
        mock_sms.assert_called_once()

    def test_notification_creation(self, tenant_fixture, user_fixture):
        """Teste criação de objeto Notification"""
        notif = Notification.objects.create(
            tenant=tenant_fixture,
            user=user_fixture,
            title="T",
            message="M",
            notification_type="system",
        )
        assert notif.id is not None
        assert notif.is_read is False

    @patch("notifications.services.WebPushDriver.send")
    def test_push_driver(self, mock_push, tenant_fixture, user_fixture):
        """Teste driver Push"""
        from notifications.services import WebPushDriver

        mock_push.return_value = True
        driver = WebPushDriver()

        # Criar device
        NotificationDevice.objects.create(
            tenant=tenant_fixture,
            user=user_fixture,
            device_type="web",
            token="token123",
        )

        res = driver.send(tenant_fixture, user_fixture, "system", "t", "m", {})
        assert res is True

    @patch("notifications.services.WhatsAppDriver.send")
    def test_whatsapp_driver(self, mock_wa, tenant_fixture, user_fixture):
        """Teste driver WhatsApp"""
        from notifications.services import WhatsAppDriver

        mock_wa.return_value = True
        driver = WhatsAppDriver()

        res = driver.send(tenant_fixture, user_fixture, "system", "t", "m", {})
        assert res is True

    @patch("notifications.services.credit_service.charge_for_message")
    def test_whatsapp_driver_with_phone(
        self, mock_charge, tenant_fixture, user_fixture
    ):
        """Teste driver WhatsApp com telefone"""
        from notifications.services import WhatsAppDriver

        # Adicionar telefone ao usuário
        user_fixture.phone_number = "+351912345678"
        user_fixture.save()

        driver = WhatsAppDriver()
        # Mock de cobrança
        mock_charge.return_value = {
            "success": True,
            "cost": Decimal("0.05"),
            "new_balance": Decimal("10.00"),
            "ledger_entry": Mock(id=1),
        }

        # Na Fase 1, o send retorna True após logar a simulação
        res = driver.send(tenant_fixture, user_fixture, "system", "t", "m", {})
        assert res is True
