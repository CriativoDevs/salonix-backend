import pytest
from django.core.cache import cache
from django.contrib.auth import get_user_model
from notifications.services import SMSDriver

User = get_user_model()


@pytest.mark.django_db
def test_sms_minute_limit_basic(tenant_fixture):
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
