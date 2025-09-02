"""
Testes para funcionalidades multi-tenant
"""

import pytest
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from users.models import Tenant
from core.models import Service, Professional, ScheduleSlot, Appointment


User = get_user_model()


class MultiTenantTestCase(TestCase):
    """Base test case com setup multi-tenant"""

    def setUp(self):
        # Usar o tenant padrão do conftest.py global
        self.tenant1, _ = Tenant.objects.get_or_create(
            slug="test-default",
            defaults={
                "name": "Test Default Salon",
                "primary_color": "#3B82F6",
                "secondary_color": "#1F2937",
            },
        )

        # Criar um segundo tenant para testes de isolamento
        self.tenant2 = Tenant.objects.create(
            name="Studio Hair",
            slug="studio-hair",
            primary_color="#45B7D1",
            secondary_color="#96CEB4",
        )

        # Criar usuários para cada tenant
        self.user1 = User.objects.create_user(
            username="salon1_owner",
            email="owner1@salon.com",
            password="testpass123",
            tenant=self.tenant1,
        )

        self.user2 = User.objects.create_user(
            username="salon2_owner",
            email="owner2@salon.com",
            password="testpass123",
            tenant=self.tenant2,
        )

        # Criar clientes para cada tenant
        self.client1 = User.objects.create_user(
            username="client1",
            email="client1@test.com",
            password="testpass123",
            tenant=self.tenant1,
        )

        self.client2 = User.objects.create_user(
            username="client2",
            email="client2@test.com",
            password="testpass123",
            tenant=self.tenant2,
        )


class TenantIsolationServiceTest(MultiTenantTestCase):
    """Testa isolamento de Services por tenant"""

    def setUp(self):
        super().setUp()

        # Serviços do tenant 1
        self.service1 = Service.objects.create(
            tenant=self.tenant1,
            user=self.user1,
            name="Corte Masculino",
            duration_minutes=30,
            price_eur=15.00,
        )

        # Serviços do tenant 2
        self.service2 = Service.objects.create(
            tenant=self.tenant2,
            user=self.user2,
            name="Corte Feminino",
            duration_minutes=45,
            price_eur=25.00,
        )

        self.api_client = APIClient()

    def test_user_can_only_see_own_tenant_services(self):
        """Usuário só vê serviços do próprio tenant"""
        self.api_client.force_authenticate(user=self.user1)

        response = self.api_client.get("/api/services/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        services = (
            response.json()["results"]
            if "results" in response.json()
            else response.json()
        )

        # Deve ver apenas serviços do tenant1
        service_ids = [s["id"] for s in services]
        self.assertIn(self.service1.id, service_ids)
        self.assertNotIn(self.service2.id, service_ids)

    def test_user_cannot_access_other_tenant_service(self):
        """Usuário não pode acessar serviço de outro tenant"""
        self.api_client.force_authenticate(user=self.user1)

        # Tentar acessar serviço do tenant2
        response = self.api_client.get(f"/api/services/{self.service2.id}/")

        # Deve retornar 404 (não encontrado) ou 403 (proibido)
        self.assertIn(
            response.status_code, [status.HTTP_404_NOT_FOUND, status.HTTP_403_FORBIDDEN]
        )

    def test_service_creation_auto_assigns_tenant(self):
        """Serviço criado é automaticamente atribuído ao tenant do usuário"""
        self.api_client.force_authenticate(user=self.user1)

        data = {"name": "Barba", "duration_minutes": 20, "price_eur": "10.00"}

        response = self.api_client.post("/api/services/", data)

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        # Verificar se foi criado com o tenant correto
        service = Service.objects.get(id=response.json()["id"])
        self.assertEqual(service.tenant, self.tenant1)
        self.assertEqual(service.user, self.user1)


class TenantIsolationProfessionalTest(MultiTenantTestCase):
    """Testa isolamento de Professionals por tenant"""

    def setUp(self):
        super().setUp()

        self.professional1 = Professional.objects.create(
            tenant=self.tenant1,
            user=self.user1,
            name="João Silva",
            bio="Barbeiro experiente",
        )

        self.professional2 = Professional.objects.create(
            tenant=self.tenant2,
            user=self.user2,
            name="Maria Santos",
            bio="Cabeleireira especializada",
        )

        self.api_client = APIClient()

    def test_professional_tenant_isolation(self):
        """Profissionais são isolados por tenant"""
        self.api_client.force_authenticate(user=self.user1)

        response = self.api_client.get("/api/professionals/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        professionals = (
            response.json()["results"]
            if "results" in response.json()
            else response.json()
        )

        professional_ids = [p["id"] for p in professionals]
        self.assertIn(self.professional1.id, professional_ids)
        self.assertNotIn(self.professional2.id, professional_ids)


class TenantIsolationAppointmentTest(MultiTenantTestCase):
    """Testa isolamento de Appointments por tenant"""

    def setUp(self):
        super().setUp()

        # Criar estrutura para tenant1
        self.service1 = Service.objects.create(
            tenant=self.tenant1,
            user=self.user1,
            name="Corte",
            duration_minutes=30,
            price_eur=15.00,
        )

        self.professional1 = Professional.objects.create(
            tenant=self.tenant1, user=self.user1, name="João"
        )

        self.slot1 = ScheduleSlot.objects.create(
            tenant=self.tenant1,
            professional=self.professional1,
            start_time="2024-12-01 10:00:00+00:00",
            end_time="2024-12-01 10:30:00+00:00",
        )

        self.appointment1 = Appointment.objects.create(
            tenant=self.tenant1,
            client=self.client1,
            service=self.service1,
            professional=self.professional1,
            slot=self.slot1,
        )

        # Criar estrutura para tenant2
        self.service2 = Service.objects.create(
            tenant=self.tenant2,
            user=self.user2,
            name="Corte Premium",
            duration_minutes=45,
            price_eur=25.00,
        )

        self.professional2 = Professional.objects.create(
            tenant=self.tenant2, user=self.user2, name="Maria"
        )

        self.slot2 = ScheduleSlot.objects.create(
            tenant=self.tenant2,
            professional=self.professional2,
            start_time="2024-12-01 14:00:00+00:00",
            end_time="2024-12-01 14:45:00+00:00",
        )

        self.appointment2 = Appointment.objects.create(
            tenant=self.tenant2,
            client=self.client2,
            service=self.service2,
            professional=self.professional2,
            slot=self.slot2,
        )

        self.api_client = APIClient()

    def test_client_sees_only_own_tenant_appointments(self):
        """Cliente vê apenas agendamentos do próprio tenant"""
        self.api_client.force_authenticate(user=self.client1)

        response = self.api_client.get("/api/me/appointments/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        appointments = (
            response.json()["results"]
            if "results" in response.json()
            else response.json()
        )

        appointment_ids = [a["id"] for a in appointments]
        self.assertIn(self.appointment1.id, appointment_ids)
        self.assertNotIn(self.appointment2.id, appointment_ids)

    def test_salon_sees_only_own_tenant_appointments(self):
        """Salão vê apenas agendamentos do próprio tenant"""
        self.api_client.force_authenticate(user=self.user1)

        response = self.api_client.get("/api/salon/appointments/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        appointments = (
            response.json()["results"]
            if "results" in response.json()
            else response.json()
        )

        appointment_ids = [a["id"] for a in appointments]
        self.assertIn(self.appointment1.id, appointment_ids)
        self.assertNotIn(self.appointment2.id, appointment_ids)

    def test_appointment_creation_with_tenant_validation(self):
        """Criação de agendamento valida tenant dos objetos relacionados"""
        self.api_client.force_authenticate(user=self.client1)

        # Tentar criar agendamento com serviço de outro tenant (deve falhar)
        data = {
            "service": self.service2.id,  # Serviço do tenant2
            "professional": self.professional1.id,  # Professional do tenant1
            "slot": self.slot1.id,
        }

        response = self.api_client.post("/api/appointments/", data)

        # Deve falhar por inconsistência de tenant
        self.assertNotEqual(response.status_code, status.HTTP_201_CREATED)


class TenantModelTest(MultiTenantTestCase):
    """Testa o modelo Tenant"""

    def test_tenant_creation(self):
        """Tenant é criado corretamente"""
        tenant = Tenant.objects.create(
            name="Novo Salão",
            slug="novo-salao",
            primary_color="#FF5733",
            secondary_color="#C70039",
        )

        self.assertEqual(tenant.name, "Novo Salão")
        self.assertEqual(tenant.slug, "novo-salao")
        self.assertTrue(tenant.is_active)
        self.assertEqual(tenant.currency, "EUR")
        self.assertEqual(tenant.timezone, "Europe/Lisbon")

    def test_tenant_str_representation(self):
        """String representation do tenant"""
        self.assertEqual(str(self.tenant1), "Test Default Salon")

    def test_user_tenant_relationship(self):
        """Relacionamento entre User e Tenant"""
        self.assertEqual(self.user1.tenant, self.tenant1)
        self.assertIn(self.user1, self.tenant1.users.all())

    def test_service_tenant_relationship(self):
        """Relacionamento entre Service e Tenant"""
        service = Service.objects.create(
            tenant=self.tenant1,
            user=self.user1,
            name="Teste",
            duration_minutes=30,
            price_eur=20.00,
        )

        self.assertEqual(service.tenant, self.tenant1)
        self.assertIn(service, self.tenant1.services.all())


class TenantPublicViewsTest(MultiTenantTestCase):
    """Testa views públicas com tenant"""

    def setUp(self):
        super().setUp()

        self.service1 = Service.objects.create(
            tenant=self.tenant1,
            user=self.user1,
            name="Corte Público",
            duration_minutes=30,
            price_eur=15.00,
        )

        self.professional1 = Professional.objects.create(
            tenant=self.tenant1, user=self.user1, name="João Público"
        )

        self.api_client = APIClient()

    def test_public_services_with_tenant_header(self):
        """View pública de serviços filtra por tenant via header"""
        response = self.api_client.get(
            "/api/public/services/", HTTP_X_TENANT_SLUG="test-default"
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        services = response.json()

        self.assertTrue(len(services) > 0)
        self.assertEqual(services[0]["name"], "Corte Público")

    def test_public_services_with_tenant_param(self):
        """View pública de serviços filtra por tenant via parâmetro"""
        response = self.api_client.get("/api/public/services/?tenant=test-default")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        services = response.json()

        self.assertTrue(len(services) > 0)

    def test_public_services_without_tenant_returns_empty(self):
        """View pública sem tenant retorna lista vazia"""
        response = self.api_client.get("/api/public/services/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        services = response.json()

        self.assertEqual(len(services), 0)
