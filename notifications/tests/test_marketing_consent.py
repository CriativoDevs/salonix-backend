import pytest

from notifications.services import notification_service
from core.models import SalonCustomer, CustomerCommunicationConsent
from notifications.models import Notification, NotificationLog


@pytest.mark.django_db
class TestMarketingConsentIntegration:
    def test_marketing_without_consent_is_skipped(self, tenant_fixture, user_fixture):
        customer = SalonCustomer.objects.create(tenant=tenant_fixture, name="Cliente X")
        results = notification_service.send_notification(
            tenant=tenant_fixture,
            user=user_fixture,
            channels=["in_app"],
            notification_type="marketing_news",
            title="Promoção",
            message="Descontos especiais",
            metadata={"purpose": "marketing", "customer_id": customer.id},
        )
        assert results["in_app"] is False
        assert (
            Notification.objects.filter(
                tenant=tenant_fixture, user=user_fixture, title="Promoção"
            ).count()
            == 0
        )
        log = NotificationLog.objects.filter(
            tenant=tenant_fixture, user=user_fixture, channel="in_app"
        ).last()
        assert log is not None and log.status == "skipped"

    def test_marketing_with_consent_allows(self, tenant_fixture, user_fixture):
        customer = SalonCustomer.objects.create(tenant=tenant_fixture, name="Cliente Y")
        CustomerCommunicationConsent.objects.create(
            tenant=tenant_fixture,
            customer=customer,
            channel="in_app",
            purpose="marketing",
            status="consented",
        )
        results = notification_service.send_notification(
            tenant=tenant_fixture,
            user=user_fixture,
            channels=["in_app"],
            notification_type="marketing_news",
            title="Promoção 2",
            message="Novos descontos",
            metadata={"purpose": "marketing", "customer_id": customer.id},
        )
        assert results["in_app"] is True
        assert Notification.objects.filter(
            tenant=tenant_fixture, user=user_fixture, title="Promoção 2"
        ).exists()

    def test_transactional_ignores_consent(self, tenant_fixture, user_fixture):
        customer = SalonCustomer.objects.create(tenant=tenant_fixture, name="Cliente Z")
        results = notification_service.send_notification(
            tenant=tenant_fixture,
            user=user_fixture,
            channels=["in_app"],
            notification_type="appointment_created",
            title="Agendamento",
            message="Confirmação",
            metadata={"purpose": "transactional", "customer_id": customer.id},
        )
        assert results["in_app"] is True
        assert Notification.objects.filter(
            tenant=tenant_fixture, user=user_fixture, title="Agendamento"
        ).exists()
