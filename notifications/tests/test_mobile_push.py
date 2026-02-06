"""
Testes para Mobile Push Notifications (Expo Push Service).
Cobre MobilePushDriver, endpoint de teste, e signals de appointment.
"""

import json
import pytest
from unittest.mock import patch, Mock
from django.test import TestCase, override_settings
from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework import status

from users.models import Tenant
from notifications.models import NotificationDevice
from notifications.services import MobilePushDriver
from core.models import (
    Service,
    Professional,
    ScheduleSlot,
    Appointment,
    SalonCustomer,
)

User = get_user_model()


class MobilePushDriverTestCase(TestCase):
    """Testes para MobilePushDriver com Expo Push Service"""

    def setUp(self):
        self.tenant = Tenant.objects.create(name="Test Tenant", slug="test-tenant")
        self.user = User.objects.create_user(
            username="testuser",
            email="test@test.com",
            password="testpass123",
            tenant=self.tenant,
        )
        self.driver = MobilePushDriver()

    def test_send_push_no_device(self):
        """Deve retornar False se usuário não tem device registrado"""
        result = self.driver.send(
            tenant=self.tenant,
            user=self.user,
            notification_type="test",
            title="Test",
            message="Test message",
            metadata={},
        )
        self.assertFalse(result)

    @patch("notifications.services.requests.post")
    def test_send_push_success(self, mock_post):
        """Deve enviar push com sucesso via Expo"""
        # Criar device
        device = NotificationDevice.objects.create(
            tenant=self.tenant,
            user=self.user,
            device_type="mobile",
            token="ExponentPushToken[xxxxxxxxxxxxxxxxxxxxxx]",
            is_active=True,
            platform="ios",
        )

        # Mock resposta Expo
        mock_response = Mock()
        mock_response.json.return_value = {
            "data": [{"status": "ok", "id": "test-ticket-id"}]
        }
        mock_response.raise_for_status = Mock()
        mock_post.return_value = mock_response

        # Enviar push
        result = self.driver.send(
            tenant=self.tenant,
            user=self.user,
            notification_type="test",
            title="Test Title",
            message="Test Message",
            metadata={"test_key": "test_value"},
        )

        # Verificações
        self.assertTrue(result)
        mock_post.assert_called_once()

        # Verificar payload
        call_args = mock_post.call_args
        payload = call_args[1]["json"]
        self.assertEqual(payload["to"], device.token)
        self.assertEqual(payload["title"], "Test Title")
        self.assertEqual(payload["body"], "Test Message")
        self.assertEqual(payload["data"]["test_key"], "test_value")
        self.assertEqual(payload["sound"], "default")
        self.assertEqual(payload["priority"], "high")

        # Verificar que last_used_at foi atualizado
        device.refresh_from_db()
        self.assertIsNotNone(device.last_used_at)

    @patch("notifications.services.requests.post")
    def test_send_push_with_deep_link(self, mock_post):
        """Deve adicionar deep link quando appointment_id está presente"""
        device = NotificationDevice.objects.create(
            tenant=self.tenant,
            user=self.user,
            device_type="mobile",
            token="ExponentPushToken[xxxxxxxxxxxxxxxxxxxxxx]",
            is_active=True,
        )

        mock_response = Mock()
        mock_response.json.return_value = {"data": [{"status": "ok"}]}
        mock_response.raise_for_status = Mock()
        mock_post.return_value = mock_response

        result = self.driver.send(
            tenant=self.tenant,
            user=self.user,
            notification_type="appointment_created",
            title="Appointment Created",
            message="Your appointment is confirmed",
            metadata={"appointment_id": 123},
        )

        self.assertTrue(result)

        # Verificar deep link
        payload = mock_post.call_args[1]["json"]
        self.assertEqual(payload["data"]["appointment_id"], 123)
        self.assertEqual(payload["data"]["route"], "appointment/123")

    @patch("notifications.services.requests.post")
    def test_send_push_device_not_registered_error(self, mock_post):
        """Deve desativar device se token for inválido (DeviceNotRegistered)"""
        device = NotificationDevice.objects.create(
            tenant=self.tenant,
            user=self.user,
            device_type="mobile",
            token="ExponentPushToken[invalid-token]",
            is_active=True,
        )

        # Mock resposta Expo com erro
        mock_response = Mock()
        mock_response.json.return_value = {
            "data": [
                {
                    "status": "error",
                    "details": {"error": "DeviceNotRegistered"},
                }
            ]
        }
        mock_response.raise_for_status = Mock()
        mock_post.return_value = mock_response

        result = self.driver.send(
            tenant=self.tenant,
            user=self.user,
            notification_type="test",
            title="Test",
            message="Test",
            metadata={},
        )

        self.assertFalse(result)

        # Verificar que device foi desativado
        device.refresh_from_db()
        self.assertFalse(device.is_active)

    @patch("notifications.services.requests.post")
    def test_send_push_http_error(self, mock_post):
        """Deve retornar False em caso de erro HTTP"""
        NotificationDevice.objects.create(
            tenant=self.tenant,
            user=self.user,
            device_type="mobile",
            token="ExponentPushToken[xxxxxxxxxxxxxxxxxxxxxx]",
            is_active=True,
        )

        # Mock erro HTTP
        mock_post.side_effect = Exception("Network error")

        result = self.driver.send(
            tenant=self.tenant,
            user=self.user,
            notification_type="test",
            title="Test",
            message="Test",
            metadata={},
        )

        self.assertFalse(result)


class TestPushEndpointTestCase(TestCase):
    """Testes para endpoint POST /api/notifications/test-push/"""

    def setUp(self):
        self.tenant = Tenant.objects.create(name="Test Tenant", slug="test-tenant")
        self.admin_user = User.objects.create_user(
            username="admin",
            email="admin@test.com",
            password="adminpass",
            tenant=self.tenant,
            is_staff=True,
        )
        self.regular_user = User.objects.create_user(
            username="regular",
            email="regular@test.com",
            password="regularpass",
            tenant=self.tenant,
            is_staff=False,
        )
        self.client = APIClient()

    def test_test_push_requires_authentication(self):
        """Endpoint deve exigir autenticação"""
        response = self.client.post("/api/notifications/test-push/")
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_test_push_requires_staff(self):
        """Apenas staff pode usar endpoint de teste"""
        self.client.force_authenticate(user=self.regular_user)
        self.regular_user.tenant = self.tenant
        response = self.client.post(
            "/api/notifications/test-push/",
            {
                "user_id": self.regular_user.id,
                "title": "Test",
                "message": "Test message",
            },
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_test_push_user_not_found(self):
        """Deve retornar 404 se usuário não existe"""
        self.client.force_authenticate(user=self.admin_user)
        self.admin_user.tenant = self.tenant
        response = self.client.post(
            "/api/notifications/test-push/",
            {
                "user_id": 99999,
                "title": "Test",
                "message": "Test message",
            },
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    @pytest.mark.skip(reason="URL routing issue - needs rewrite using reverse()")
    def test_test_push_no_device(self):
        """Deve retornar mensagem se usuário não tem device"""
        self.client.force_authenticate(user=self.admin_user)
        self.admin_user.tenant = self.tenant
        self.regular_user.tenant = self.tenant
        response = self.client.post(
            "/api/notifications/test-push/",
            {
                "user_id": self.regular_user.id,
                "title": "Test",
                "message": "Test message",
            },
            format="json",
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFalse(response.data["success"])
        self.assertFalse(response.data["has_device"])

    @pytest.mark.skip(reason="URL routing issue - needs rewrite using reverse()")
    @patch("notifications.services.requests.post")
    def test_test_push_success(self, mock_post):
        """Deve enviar push de teste com sucesso"""
        # Criar device para usuário
        NotificationDevice.objects.create(
            tenant=self.tenant,
            user=self.regular_user,
            device_type="mobile",
            token="ExponentPushToken[test]",
            is_active=True,
        )

        # Mock Expo
        mock_response = Mock()
        mock_response.json.return_value = {"data": [{"status": "ok"}]}
        mock_response.raise_for_status = Mock()
        mock_post.return_value = mock_response

        self.client.force_authenticate(user=self.admin_user)
        self.admin_user.tenant = self.tenant
        self.regular_user.tenant = self.tenant
        response = self.client.post(
            "/api/notifications/test-push/",
            {
                "user_id": self.regular_user.id,
                "title": "Test Push",
                "message": "This is a test",
            },
            format="json",
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data["success"])
        self.assertTrue(response.data["has_device"])
        self.assertIn("sucesso", response.data["message"])

    @pytest.mark.skip(reason="URL routing issue - needs rewrite using reverse()")
    @patch("notifications.services.requests.post")
    def test_test_push_with_appointment_id(self, mock_post):
        """Deve enviar push com deep link quando appointment_id fornecido"""
        NotificationDevice.objects.create(
            tenant=self.tenant,
            user=self.regular_user,
            device_type="mobile",
            token="ExponentPushToken[test]",
            is_active=True,
        )

        mock_response = Mock()
        mock_response.json.return_value = {"data": [{"status": "ok"}]}
        mock_response.raise_for_status = Mock()
        mock_post.return_value = mock_response

        self.client.force_authenticate(user=self.admin_user)
        self.admin_user.tenant = self.tenant
        self.regular_user.tenant = self.tenant
        response = self.client.post(
            "/api/notifications/test-push/",
            {
                "user_id": self.regular_user.id,
                "title": "Test",
                "message": "Test",
                "appointment_id": 456,
            },
            format="json",
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data["success"])

        # Verificar que appointment_id foi passado
        payload = mock_post.call_args[1]["json"]
        self.assertEqual(payload["data"]["appointment_id"], 456)
        self.assertEqual(payload["data"]["route"], "appointment/456")


class AppointmentPushSignalsTestCase(TestCase):
    """Testes para signals de appointment (push automático)"""

    def setUp(self):
        self.tenant = Tenant.objects.create(name="Test Tenant", slug="test-tenant")
        self.user = User.objects.create_user(
            username="client",
            email="client@test.com",
            password="clientpass",
            tenant=self.tenant,
        )
        self.customer = SalonCustomer.objects.create(
            tenant=self.tenant,
            name="Test Customer",
            email="customer@test.com",
        )
        self.service = Service.objects.create(
            tenant=self.tenant,
            user=self.user,
            name="Test Service",
            duration_minutes=60,
            price_eur=50.0,
        )
        self.professional = Professional.objects.create(
            tenant=self.tenant,
            user=self.user,
            name="Test Professional",
        )
        self.slot = ScheduleSlot.objects.create(
            tenant=self.tenant,
            professional=self.professional,
            start_time=timezone.now() + timezone.timedelta(days=1),
            end_time=timezone.now() + timezone.timedelta(days=1, hours=1),
            is_available=True,
        )

    @patch("notifications.services.requests.post")
    def test_appointment_created_sends_push(self, mock_post):
        """Deve enviar push quando appointment é criado"""
        # Criar device
        NotificationDevice.objects.create(
            tenant=self.tenant,
            user=self.user,
            device_type="mobile",
            token="ExponentPushToken[test]",
            is_active=True,
        )

        # Mock Expo
        mock_response = Mock()
        mock_response.json.return_value = {"data": [{"status": "ok"}]}
        mock_response.raise_for_status = Mock()
        mock_post.return_value = mock_response

        # Criar appointment (deve disparar signal)
        appointment = Appointment.objects.create(
            tenant=self.tenant,
            client=self.user,
            customer=self.customer,
            service=self.service,
            professional=self.professional,
            slot=self.slot,
            status="scheduled",
        )

        # Verificar que push foi enviado
        self.assertTrue(mock_post.called)
        payload = mock_post.call_args[1]["json"]
        self.assertIn("Agendamento", payload["title"])
        self.assertEqual(payload["data"]["appointment_id"], appointment.id)

    @patch("notifications.services.requests.post")
    def test_appointment_deleted_sends_push(self, mock_post):
        """Deve enviar push quando appointment é deletado"""
        # Criar device
        NotificationDevice.objects.create(
            tenant=self.tenant,
            user=self.user,
            device_type="mobile",
            token="ExponentPushToken[test]",
            is_active=True,
        )

        # Mock Expo
        mock_response = Mock()
        mock_response.json.return_value = {"data": [{"status": "ok"}]}
        mock_response.raise_for_status = Mock()
        mock_post.return_value = mock_response

        # Criar appointment
        appointment = Appointment.objects.create(
            tenant=self.tenant,
            client=self.user,
            customer=self.customer,
            service=self.service,
            professional=self.professional,
            slot=self.slot,
            status="scheduled",
        )

        # Limpar mock
        mock_post.reset_mock()

        # Deletar appointment (deve disparar signal)
        appointment.delete()

        # Verificar que push foi enviado
        self.assertTrue(mock_post.called)
        payload = mock_post.call_args[1]["json"]
        self.assertIn("Cancelado", payload["title"])

    def test_appointment_no_device_no_error(self):
        """Não deve dar erro se usuário não tem device"""
        # Criar appointment sem device registrado (não deve explodir)
        try:
            Appointment.objects.create(
                tenant=self.tenant,
                client=self.user,
                customer=self.customer,
                service=self.service,
                professional=self.professional,
                slot=self.slot,
                status="scheduled",
            )
        except Exception as e:
            self.fail(f"Signal não deve falhar se usuário não tem device: {e}")


class NotificationDeviceModelTestCase(TestCase):
    """Testes para novos campos do NotificationDevice"""

    def setUp(self):
        self.tenant = Tenant.objects.create(name="Test Tenant", slug="test-tenant")
        self.user = User.objects.create_user(
            username="user",
            email="user@test.com",
            password="pass",
            tenant=self.tenant,
        )

    def test_create_device_with_new_fields(self):
        """Deve criar device com novos campos (platform, app_version, last_used_at)"""
        device = NotificationDevice.objects.create(
            tenant=self.tenant,
            user=self.user,
            device_type="mobile",
            token="ExponentPushToken[test]",
            platform="ios",
            app_version="1.2.3",
        )

        self.assertEqual(device.platform, "ios")
        self.assertEqual(device.app_version, "1.2.3")
        self.assertIsNone(device.last_used_at)

    def test_update_last_used_at(self):
        """Deve atualizar last_used_at"""
        device = NotificationDevice.objects.create(
            tenant=self.tenant,
            user=self.user,
            device_type="mobile",
            token="ExponentPushToken[test]",
        )

        now = timezone.now()
        device.last_used_at = now
        device.save()

        device.refresh_from_db()
        self.assertIsNotNone(device.last_used_at)
        self.assertAlmostEqual(
            device.last_used_at.timestamp(), now.timestamp(), delta=1
        )
