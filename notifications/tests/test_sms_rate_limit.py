from unittest.mock import patch, MagicMock
from decimal import Decimal
import pytest
from django.core.cache import cache
from django.contrib.auth import get_user_model
from django.conf import settings
from notifications.services import SMSDriver

User = get_user_model()


@pytest.mark.django_db
@patch("notifications.services.credit_service.charge_for_message")
@patch("notifications.services.TwilioClient")
def test_sms_minute_limit_basic(mock_twilio, mock_charge, tenant_fixture, settings):
    # Forçar SMS habilitado e credenciais fakes para o teste
    settings.SMS_ENABLED = True
    settings.TWILIO_ACCOUNT_SID = "ACxxx"
    settings.TWILIO_AUTH_TOKEN = "token"
    settings.TWILIO_MESSAGING_SERVICE_SID = "MGxxx"

    # Mock de cobrança bem sucedida
    mock_charge.return_value = {
        "success": True,
        "cost": Decimal("0.09"),
        "new_balance": Decimal("10.00"),
        "ledger_entry": MagicMock(id=1)
    }
    
    # Mock do cliente Twilio
    mock_msg = MagicMock()
    mock_msg.sid = "SMxxx"
    mock_twilio.return_value.messages.create.return_value = mock_msg

    # Limpar cache para janelas limpas
    try:
        cache.clear()
    except Exception:
        pass

    # Configurar tenant como BASIC (3 por minuto)
    tenant_fixture.plan_tier = "basic"
    tenant_fixture.sms_enabled = True
    tenant_fixture.save(update_fields=["plan_tier", "sms_enabled"])

    # Usuário com telefone
    user = User.objects.create_user(username="smsuser", email="sms@example.com", password="pass")
    user.phone_number = "+351911111111"
    user.tenant = tenant_fixture
    user.save(update_fields=["phone_number", "tenant"])

    driver = SMSDriver()

    # 1..3 devem passar
    assert driver.send(
        tenant=tenant_fixture,
        user=user,
        notification_type="test",
        title="t",
        message="m",
        metadata={},
    ) is True
    assert driver.send(
        tenant=tenant_fixture,
        user=user,
        notification_type="test",
        title="t",
        message="m",
        metadata={},
    ) is True
    assert driver.send(
        tenant=tenant_fixture,
        user=user,
        notification_type="test",
        title="t",
        message="m",
        metadata={},
    ) is True

    # 4º no mesmo minuto deve ser bloqueado
    assert (
        driver.send(
            tenant=tenant_fixture,
            user=user,
            notification_type="test",
            title="t",
            message="m",
            metadata={},
        )
        is False
    )
