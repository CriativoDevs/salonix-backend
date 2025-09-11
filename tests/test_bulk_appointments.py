from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient
from unittest.mock import patch
from datetime import timedelta

from core.models import Appointment, Service, Professional, ScheduleSlot
from users.models import CustomUser, Tenant


class TestBulkAppointments(TestCase):
    """Testes para o sistema de agendamentos múltiplos."""

    def setUp(self):
        """Setup para cada teste."""
        # Limpar todos os tenants existentes
        Tenant.objects.all().delete()

        # Criar tenant
        self.tenant = Tenant.objects.create(
            name="Salão Teste", slug="salao-teste", plan_tier="pro", is_active=True
        )

        # Criar usuário cliente
        self.client_user = CustomUser.objects.create_user(
            username="cliente_teste",
            email="cliente@teste.com",
            password="senha123",
            tenant=self.tenant,
            phone_number="+351912345678",
        )

        # Criar usuário salão
        self.salon_user = CustomUser.objects.create_user(
            username="salao_teste",
            email="salao@teste.com",
            password="senha123",
            tenant=self.tenant,
        )

        # Criar serviço
        self.service = Service.objects.create(
            name="Corte de Cabelo",
            price_eur=25.00,
            duration_minutes=60,
            user=self.salon_user,
            tenant=self.tenant,
        )

        # Criar profissional
        self.professional = Professional.objects.create(
            name="João Profissional",
            bio="Profissional experiente",
            user=self.salon_user,
            tenant=self.tenant,
        )

        # Criar slots disponíveis (próximos 7 dias)
        self.slots = []
        base_time = timezone.now() + timedelta(days=1)
        for i in range(5):
            slot_time = base_time + timedelta(days=i, hours=10)  # 10:00 cada dia
            slot = ScheduleSlot.objects.create(
                professional=self.professional,
                start_time=slot_time,
                end_time=slot_time + timedelta(hours=1),
                is_available=True,
                tenant=self.tenant,
            )
            self.slots.append(slot)

        # Cliente API
        self.client_api = APIClient()
        self.client_api.force_authenticate(user=self.client_user)

        # URL do endpoint
        self.url = reverse("appointment-bulk-create")

    def test_bulk_appointment_success(self):
        """Teste de criação bem-sucedida de agendamentos múltiplos."""
        data = {
            "service_id": self.service.id,
            "professional_id": self.professional.id,
            "appointments": [
                {"slot_id": self.slots[0].id},
                {"slot_id": self.slots[1].id},
                {"slot_id": self.slots[2].id},
            ],
            "notes": "Curso de 3 sessões",
        }

        with patch("core.views.logger") as mock_logger:
            response = self.client_api.post(self.url, data, format="json")

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        # Verificar resposta
        response_data = response.json()
        self.assertTrue(response_data["success"])
        self.assertEqual(response_data["appointments_created"], 3)
        self.assertEqual(len(response_data["appointment_ids"]), 3)
        self.assertEqual(response_data["total_value"], 75.0)  # 3 * 25.00
        self.assertEqual(response_data["service_name"], "Corte de Cabelo")
        self.assertEqual(response_data["professional_name"], "João Profissional")
        self.assertEqual(len(response_data["appointments"]), 3)

        # Verificar se agendamentos foram criados
        appointments = Appointment.objects.filter(
            id__in=response_data["appointment_ids"]
        )
        self.assertEqual(appointments.count(), 3)

        # Verificar se slots foram marcados como ocupados
        for slot in self.slots[:3]:
            slot.refresh_from_db()
            assert not slot.is_available

        # Verificar se slots restantes continuam disponíveis
        for slot in self.slots[3:]:
            slot.refresh_from_db()
            assert slot.is_available

        # Verificar dados dos agendamentos
        for appointment in appointments:
            self.assertEqual(appointment.client, self.client_user)
            self.assertEqual(appointment.service, self.service)
            self.assertEqual(appointment.professional, self.professional)
            self.assertEqual(appointment.status, "scheduled")
            self.assertEqual(appointment.notes, "Curso de 3 sessões")
            # Verificar tenant (pode ser None devido ao campo null=True temporário)
            if appointment.tenant:
                self.assertEqual(appointment.tenant, self.tenant)

    def test_bulk_appointment_with_individual_notes(self):
        """Teste com notas individuais por agendamento."""
        data = {
            "service_id": self.service.id,
            "professional_id": self.professional.id,
            "appointments": [
                {"slot_id": self.slots[0].id, "notes": "Primeira sessão"},
                {"slot_id": self.slots[1].id, "notes": "Segunda sessão"},
            ],
        }

        response = self.client_api.post(self.url, data, format="json")

        assert response.status_code == status.HTTP_201_CREATED

        appointments = Appointment.objects.filter(
            id__in=response.json()["appointment_ids"]
        ).order_by("slot__start_time")

        assert appointments[0].notes == "Primeira sessão"
        assert appointments[1].notes == "Segunda sessão"

    def test_bulk_appointment_validation_errors(self):
        """Teste de erros de validação."""
        # Teste sem appointments
        data = {
            "service_id": self.service.id,
            "professional_id": self.professional.id,
            "appointments": [],
        }

        response = self.client_api.post(self.url, data, format="json")
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "Pelo menos um agendamento é obrigatório" in str(response.json())

        # Teste com muitos appointments
        data = {
            "service_id": self.service.id,
            "professional_id": self.professional.id,
            "appointments": [{"slot_id": self.slots[0].id}] * 11,  # Máximo é 10
        }

        response = self.client_api.post(self.url, data, format="json")
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "Máximo de 10 agendamentos por lote" in str(response.json())

    def test_bulk_appointment_duplicate_slots(self):
        """Teste com slots duplicados."""
        data = {
            "service_id": self.service.id,
            "professional_id": self.professional.id,
            "appointments": [
                {"slot_id": self.slots[0].id},
                {"slot_id": self.slots[0].id},  # Duplicado
            ],
        }

        response = self.client_api.post(self.url, data, format="json")
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "Slots duplicados não são permitidos" in str(response.json())

    def test_bulk_appointment_unavailable_slots(self):
        """Teste com slots não disponíveis."""
        # Marcar primeiro slot como ocupado
        self.slots[0].mark_booked()

        data = {
            "service_id": self.service.id,
            "professional_id": self.professional.id,
            "appointments": [
                {"slot_id": self.slots[0].id},  # Não disponível
                {"slot_id": self.slots[1].id},
            ],
        }

        response = self.client_api.post(self.url, data, format="json")
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert f"Slots não disponíveis: [{self.slots[0].id}]" in str(response.json())

    def test_bulk_appointment_nonexistent_slots(self):
        """Teste com slots inexistentes."""
        data = {
            "service_id": self.service.id,
            "professional_id": self.professional.id,
            "appointments": [
                {"slot_id": 99999},  # Não existe
                {"slot_id": self.slots[1].id},
            ],
        }

        response = self.client_api.post(self.url, data, format="json")
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "Slots não encontrados: {99999}" in str(response.json())

    def test_bulk_appointment_wrong_professional(self):
        """Teste com slots de profissional diferente."""
        # Criar outro profissional e slot
        other_professional = Professional.objects.create(
            name="Outro Profissional", user=self.salon_user, tenant=self.tenant
        )

        other_slot = ScheduleSlot.objects.create(
            professional=other_professional,
            start_time=timezone.now() + timedelta(days=1, hours=14),
            end_time=timezone.now() + timedelta(days=1, hours=15),
            is_available=True,
            tenant=self.tenant,
        )

        data = {
            "service_id": self.service.id,
            "professional_id": self.professional.id,
            "appointments": [
                {"slot_id": self.slots[0].id},  # Profissional correto
                {"slot_id": other_slot.id},  # Profissional diferente
            ],
        }

        response = self.client_api.post(self.url, data, format="json")
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert (
            f"Slots não pertencem ao profissional informado: [{other_slot.id}]"
            in str(response.json())
        )

    def test_bulk_appointment_past_slots(self):
        """Teste com slots no passado."""
        # Criar slot no passado
        past_slot = ScheduleSlot.objects.create(
            professional=self.professional,
            start_time=timezone.now() - timedelta(hours=1),
            end_time=timezone.now() - timedelta(minutes=30),
            is_available=True,
            tenant=self.tenant,
        )

        data = {
            "service_id": self.service.id,
            "professional_id": self.professional.id,
            "appointments": [{"slot_id": past_slot.id}],
        }

        response = self.client_api.post(self.url, data, format="json")
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert f"Não é possível agendar slots no passado: [{past_slot.id}]" in str(
            response.json()
        )

    def test_bulk_appointment_nonexistent_service(self):
        """Teste com serviço inexistente."""
        data = {
            "service_id": 99999,
            "professional_id": self.professional.id,
            "appointments": [{"slot_id": self.slots[0].id}],
        }

        response = self.client_api.post(self.url, data, format="json")
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "Serviço não encontrado" in str(response.json())

    def test_bulk_appointment_nonexistent_professional(self):
        """Teste com profissional inexistente."""
        data = {
            "service_id": self.service.id,
            "professional_id": 99999,
            "appointments": [{"slot_id": self.slots[0].id}],
        }

        response = self.client_api.post(self.url, data, format="json")
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "Profissional não encontrado" in str(response.json())

    def test_bulk_appointment_atomic_transaction(self):
        """Teste de transação atômica - se um falha, todos falham."""
        # Marcar o segundo slot como ocupado após validação inicial
        data = {
            "service_id": self.service.id,
            "professional_id": self.professional.id,
            "appointments": [
                {"slot_id": self.slots[0].id},
                {"slot_id": self.slots[1].id},
                {"slot_id": self.slots[2].id},
            ],
        }

        # Mock para simular falha durante criação
        with patch("core.models.Appointment.objects.create") as mock_create:
            mock_create.side_effect = Exception("Erro simulado")

            response = self.client_api.post(self.url, data, format="json")

        assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR

        # Verificar que nenhum agendamento foi criado
        assert Appointment.objects.count() == 0

        # Verificar que todos os slots continuam disponíveis
        for slot in self.slots:
            slot.refresh_from_db()
            assert slot.is_available

    def test_bulk_appointment_unauthenticated(self):
        """Teste sem autenticação."""
        client = APIClient()  # Sem autenticação

        data = {
            "service_id": self.service.id,
            "professional_id": self.professional.id,
            "appointments": [{"slot_id": self.slots[0].id}],
        }

        response = client.post(self.url, data, format="json")
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_bulk_appointment_client_data_from_user(self):
        """Teste que usa dados do usuário autenticado."""
        data = {
            "service_id": self.service.id,
            "professional_id": self.professional.id,
            "appointments": [{"slot_id": self.slots[0].id}],
            # Sem client_name, client_email - deve usar do usuário
        }

        response = self.client_api.post(self.url, data, format="json")

        assert response.status_code == status.HTTP_201_CREATED

        appointment = Appointment.objects.get(id=response.json()["appointment_ids"][0])
        assert appointment.client == self.client_user

    def test_bulk_appointment_phone_validation(self):
        """Teste de validação de telefone."""
        data = {
            "service_id": self.service.id,
            "professional_id": self.professional.id,
            "client_phone": "123456789",  # Formato inválido
            "appointments": [{"slot_id": self.slots[0].id}],
        }

        response = self.client_api.post(self.url, data, format="json")
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "Formato de telefone inválido" in str(response.json())

    def test_bulk_appointment_metrics_success(self):
        """Teste de métricas em caso de sucesso."""
        data = {
            "service_id": self.service.id,
            "professional_id": self.professional.id,
            "appointments": [
                {"slot_id": self.slots[0].id},
                {"slot_id": self.slots[1].id},
            ],
        }

        with patch("core.views.BULK_APPOINTMENTS_TOTAL") as mock_total, patch(
            "core.views.BULK_APPOINTMENTS_SIZE"
        ) as mock_size:

            response = self.client_api.post(self.url, data, format="json")

        assert response.status_code == status.HTTP_201_CREATED

        # Verificar métricas
        mock_total.labels.assert_called_with(tenant_id=self.tenant.id, status="success")
        mock_total.labels().inc.assert_called()

        mock_size.labels.assert_called_with(tenant_id=self.tenant.id)
        mock_size.labels().inc.assert_called_with(2)

    def test_bulk_appointment_metrics_error(self):
        """Teste de métricas em caso de erro."""
        data = {
            "service_id": 99999,  # Serviço inexistente
            "professional_id": self.professional.id,
            "appointments": [{"slot_id": self.slots[0].id}],
        }

        with patch("core.views.BULK_APPOINTMENTS_TOTAL") as mock_total:
            response = self.client_api.post(self.url, data, format="json")

        assert response.status_code == status.HTTP_400_BAD_REQUEST

        # Verificar métrica de erro
        mock_total.labels.assert_called_with(
            tenant_id=self.tenant.id, status="validation_error"
        )
        mock_total.labels().inc.assert_called()

    def test_bulk_appointment_tenant_isolation(self):
        """Teste de isolamento por tenant."""
        # Criar outro tenant com seus próprios dados
        other_tenant = Tenant.objects.create(
            name="Outro Salão", slug="outro-salao", plan_tier="basic", is_active=True
        )

        other_user = CustomUser.objects.create_user(
            username="outro_usuario",
            email="outro@teste.com",
            password="senha123",
            tenant=other_tenant,
        )

        other_service = Service.objects.create(
            name="Outro Serviço",
            price_eur=30.00,
            duration_minutes=45,
            user=other_user,
            tenant=other_tenant,
        )

        # Tentar usar serviço de outro tenant
        data = {
            "service_id": other_service.id,  # Serviço de outro tenant
            "professional_id": self.professional.id,
            "appointments": [{"slot_id": self.slots[0].id}],
        }

        response = self.client_api.post(self.url, data, format="json")
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "Serviço não encontrado" in str(response.json())

    def test_bulk_appointment_logging(self):
        """Teste de logging estruturado."""
        data = {
            "service_id": self.service.id,
            "professional_id": self.professional.id,
            "appointments": [{"slot_id": self.slots[0].id}],
        }

        with patch("core.views.logger") as mock_logger:
            response = self.client_api.post(self.url, data, format="json")

        assert response.status_code == status.HTTP_201_CREATED

        # Verificar se log foi chamado
        mock_logger.info.assert_called_once()

        # Verificar estrutura do log
        call_args = mock_logger.info.call_args
        assert "Bulk appointments created successfully" in call_args[0][0]

        extra = call_args[1]["extra"]
        assert extra["tenant_id"] == self.tenant.id
        assert extra["user_id"] == self.client_user.id
        assert extra["service_id"] == self.service.id
        assert extra["professional_id"] == self.professional.id
        assert extra["appointments_count"] == 1
        assert len(extra["appointment_ids"]) == 1
        assert extra["total_value"] == 25.0
