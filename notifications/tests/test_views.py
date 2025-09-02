import pytest
import json
from django.urls import reverse
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient
from rest_framework import status
from users.models import Tenant
from notifications.models import Notification, NotificationDevice, NotificationLog

User = get_user_model()


@pytest.mark.django_db
class TestNotificationViews:
    """Testes para as views de notificação"""

    def setup_method(self):
        """Setup para cada teste"""
        self.client = APIClient()

    def test_notification_list_view(self, tenant_fixture, user_fixture):
        """Teste listagem de notificações"""
        # Fazer login
        self.client.force_authenticate(user=user_fixture)

        # Criar algumas notificações
        Notification.objects.create(
            tenant=tenant_fixture,
            user=user_fixture,
            notification_type="appointment_created",
            title="Agendamento 1",
            message="Mensagem 1",
        )

        Notification.objects.create(
            tenant=tenant_fixture,
            user=user_fixture,
            notification_type="system",
            title="Sistema",
            message="Mensagem sistema",
            is_read=True,
        )

        # Fazer requisição
        url = reverse("notification-list")
        response = self.client.get(url)

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert len(data) == 2

        # Verificar ordenação (mais recente primeiro)
        assert data[0]["title"] == "Sistema"
        assert data[1]["title"] == "Agendamento 1"

    def test_notification_list_filter_unread(self, tenant_fixture, user_fixture):
        """Teste filtro de notificações não lidas"""
        self.client.force_authenticate(user=user_fixture)

        # Criar notificações (uma lida, uma não lida)
        Notification.objects.create(
            tenant=tenant_fixture,
            user=user_fixture,
            notification_type="system",
            title="Lida",
            message="Mensagem lida",
            is_read=True,
        )

        Notification.objects.create(
            tenant=tenant_fixture,
            user=user_fixture,
            notification_type="system",
            title="Não Lida",
            message="Mensagem não lida",
            is_read=False,
        )

        # Filtrar apenas não lidas
        url = reverse("notification-list")
        response = self.client.get(url, {"is_read": "false"})

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert len(data) == 1
        assert data[0]["title"] == "Não Lida"
        assert data[0]["is_read"] is False

    def test_notification_mark_read(self, tenant_fixture, user_fixture):
        """Teste marcar notificação como lida"""
        self.client.force_authenticate(user=user_fixture)

        # Criar notificação não lida
        notification = Notification.objects.create(
            tenant=tenant_fixture,
            user=user_fixture,
            notification_type="system",
            title="Teste",
            message="Mensagem teste",
        )

        assert notification.is_read is False
        assert notification.read_at is None

        # Marcar como lida
        url = reverse("notification-mark-read", kwargs={"pk": notification.pk})
        response = self.client.patch(url, {"is_read": True})

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["is_read"] is True
        assert data["read_at"] is not None

        # Verificar no banco
        notification.refresh_from_db()
        assert notification.is_read is True
        assert notification.read_at is not None

    def test_notification_mark_all_read(self, tenant_fixture, user_fixture):
        """Teste marcar todas notificações como lidas"""
        self.client.force_authenticate(user=user_fixture)

        # Criar várias notificações não lidas
        for i in range(3):
            Notification.objects.create(
                tenant=tenant_fixture,
                user=user_fixture,
                notification_type="system",
                title=f"Teste {i}",
                message=f"Mensagem {i}",
            )

        # Verificar que estão não lidas
        unread_count = Notification.objects.filter(
            tenant=tenant_fixture, user=user_fixture, is_read=False
        ).count()
        assert unread_count == 3

        # Marcar todas como lidas
        url = reverse("notification-mark-all-read")
        response = self.client.post(url)

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["updated_count"] == 3

        # Verificar que foram marcadas
        unread_count = Notification.objects.filter(
            tenant=tenant_fixture, user=user_fixture, is_read=False
        ).count()
        assert unread_count == 0

    def test_register_device(self, tenant_fixture, user_fixture):
        """Teste registro de device"""
        self.client.force_authenticate(user=user_fixture)

        url = reverse("notification-register-device")
        data = {"device_type": "web", "token": "test-web-token-123", "is_active": True}

        response = self.client.post(url, data)

        assert response.status_code == status.HTTP_201_CREATED
        response_data = response.json()
        assert response_data["device_type"] == "web"
        assert response_data["token"] == "test-web-token-123"
        assert response_data["is_active"] is True

        # Verificar no banco
        device = NotificationDevice.objects.get(
            tenant=tenant_fixture, user=user_fixture, device_type="web"
        )
        assert device.token == "test-web-token-123"

    def test_register_device_duplicate(self, tenant_fixture, user_fixture):
        """Teste registro de device duplicado (deve atualizar)"""
        self.client.force_authenticate(user=user_fixture)

        # Criar device inicial
        existing_device = NotificationDevice.objects.create(
            tenant=tenant_fixture,
            user=user_fixture,
            device_type="web",
            token="old-token",
            is_active=False,
        )

        # Tentar registrar mesmo device com novo status
        url = reverse("notification-register-device")
        data = {"device_type": "web", "token": "old-token", "is_active": True}

        response = self.client.post(url, data)

        assert response.status_code == status.HTTP_201_CREATED

        # Verificar que foi atualizado (não criado novo)
        device_count = NotificationDevice.objects.filter(
            tenant=tenant_fixture,
            user=user_fixture,
            device_type="web",
            token="old-token",
        ).count()
        assert device_count == 1

        # Verificar que status foi atualizado
        existing_device.refresh_from_db()
        assert existing_device.is_active is True

    def test_notification_test_channel(self, tenant_fixture, user_fixture):
        """Teste endpoint de teste de canal"""
        self.client.force_authenticate(user=user_fixture)

        url = reverse("notification-test")
        data = {"channel": "in_app", "message": "Mensagem de teste personalizada"}

        response = self.client.post(url, data)

        assert response.status_code == status.HTTP_200_OK
        response_data = response.json()
        assert response_data["channel"] == "in_app"
        assert response_data["success"] is True

        # Verificar que notificação de teste foi criada
        notification = Notification.objects.get(
            tenant=tenant_fixture, user=user_fixture, notification_type="system"
        )
        assert notification.title == "Teste de Notificação"
        assert notification.message == "Mensagem de teste personalizada"
        assert notification.metadata["is_test"] is True

    def test_notification_stats(self, tenant_fixture, user_fixture):
        """Teste estatísticas de notificações"""
        self.client.force_authenticate(user=user_fixture)

        # Criar notificações (2 não lidas, 1 lida)
        Notification.objects.create(
            tenant=tenant_fixture,
            user=user_fixture,
            notification_type="system",
            title="Não lida 1",
            message="Mensagem 1",
        )

        Notification.objects.create(
            tenant=tenant_fixture,
            user=user_fixture,
            notification_type="system",
            title="Não lida 2",
            message="Mensagem 2",
        )

        Notification.objects.create(
            tenant=tenant_fixture,
            user=user_fixture,
            notification_type="system",
            title="Lida",
            message="Mensagem lida",
            is_read=True,
        )

        # Criar device
        NotificationDevice.objects.create(
            tenant=tenant_fixture,
            user=user_fixture,
            device_type="web",
            token="test-token",
        )

        url = reverse("notification-stats")
        response = self.client.get(url)

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["total_notifications"] == 3
        assert data["unread_notifications"] == 2
        assert data["read_notifications"] == 1
        assert data["registered_devices"] == 1

    def test_notification_unauthorized(self):
        """Teste acesso não autorizado"""
        url = reverse("notification-list")
        response = self.client.get(url)

        assert response.status_code == status.HTTP_401_UNAUTHORIZED
