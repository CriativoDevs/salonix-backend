import pytest
from django.urls import reverse
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient
from rest_framework import status
from notifications.models import Notification, NotificationDevice
from users.models import Tenant

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

    def test_register_device_same_token_different_tenants(
        self, tenant_fixture, user_fixture
    ):
        """
        Bug de produção (confirmado nos logs): quando já existe um registo de
        NotificationDevice para o mesmo (user, device_type, token) associado
        a OUTRO tenant (ex.: dados históricos de uma reatribuição de tenant,
        ou reutilização do mesmo device/token), a busca em perform_create é
        escopada ao tenant atual e não encontra esse registo. O código então
        tenta criar um novo NotificationDevice, o que colide com o índice
        único (user, device_type, token) ao nível da BD e levanta um
        IntegrityError não tratado (500 em produção).

        Cada tenant deve poder ter o seu próprio registo isolado para o mesmo
        (user, device_type, token).
        """
        other_tenant = Tenant.objects.create(
            slug="other-notif-tenant", name="Other Notif Tenant"
        )
        shared_token = "shared-cross-tenant-token"

        # Registo pré-existente do MESMO user sob um tenant DIFERENTE
        # (simula dados legados / reatribuição de tenant do usuário).
        NotificationDevice.objects.create(
            tenant=other_tenant,
            user=user_fixture,
            device_type="mobile",
            token=shared_token,
            is_active=True,
        )

        self.client.force_authenticate(user=user_fixture)
        url = reverse("notification-register-device")
        data = {"device_type": "mobile", "token": shared_token, "is_active": True}

        response = self.client.post(url, data)

        assert response.status_code == status.HTTP_201_CREATED

        # Cada tenant tem o seu próprio device, ambos com o mesmo token
        device_tenant_1 = NotificationDevice.objects.get(
            tenant=tenant_fixture, user=user_fixture, device_type="mobile"
        )
        device_tenant_2 = NotificationDevice.objects.get(
            tenant=other_tenant, user=user_fixture, device_type="mobile"
        )
        assert device_tenant_1.token == shared_token
        assert device_tenant_2.token == shared_token
        assert device_tenant_1.id != device_tenant_2.id

        assert (
            NotificationDevice.objects.filter(
                user=user_fixture, device_type="mobile", token=shared_token
            ).count()
            == 2
        )

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

    def test_notification_list_admin_app_allowed_for_basic_tenant(
        self, tenant_fixture, user_fixture
    ):
        """BE-PLANS-01 (#481): Basic absorveu apps nativos; Admin App liberado."""
        tenant_fixture.plan_tier = "basic"
        tenant_fixture.rn_admin_enabled = False
        tenant_fixture.save(
            update_fields=["plan_tier", "rn_admin_enabled", "updated_at"]
        )

        self.client.force_authenticate(user=user_fixture)
        url = reverse("notification-list")
        response = self.client.get(url, HTTP_X_APP_TYPE="admin")

        assert response.status_code == status.HTTP_200_OK

    def test_register_device_client_app_allowed_for_pro_tenant(
        self, tenant_fixture, user_fixture
    ):
        """Tenant Pro deve conseguir registrar device com X-App-Type: client."""
        self.client.force_authenticate(user=user_fixture)

        url = reverse("notification-register-device")
        data = {
            "device_type": "mobile",
            "token": "test-mobile-token-allowed",
            "is_active": True,
        }

        response = self.client.post(url, data, HTTP_X_APP_TYPE="client")

        assert response.status_code == status.HTTP_201_CREATED
        assert response.data["device_type"] == "mobile"
        assert response.data["token"] == "test-mobile-token-allowed"

    def test_register_device_client_app_allowed_for_basic_tenant(
        self, tenant_fixture, user_fixture
    ):
        """BE-PLANS-01 (#481): Basic absorveu apps nativos; Client App liberado."""
        tenant_fixture.plan_tier = "basic"
        tenant_fixture.rn_client_enabled = False
        tenant_fixture.save(
            update_fields=["plan_tier", "rn_client_enabled", "updated_at"]
        )

        self.client.force_authenticate(user=user_fixture)

        url = reverse("notification-register-device")
        data = {
            "device_type": "mobile",
            "token": "test-mobile-token-now-allowed",
            "is_active": True,
        }

        response = self.client.post(url, data, HTTP_X_APP_TYPE="client")

        assert response.status_code == status.HTTP_201_CREATED
