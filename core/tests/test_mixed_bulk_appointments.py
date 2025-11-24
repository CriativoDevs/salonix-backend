from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient
from datetime import timedelta

from core.models import (
    Appointment,
    Service,
    Professional,
    ScheduleSlot,
    ProfessionalService,
    AppointmentReservedSlot,
)
from users.models import CustomUser, Tenant


class TestMixedBulkAppointments(TestCase):
    """Testes para o endpoint mixed bulk de agendamentos."""

    def setUp(self):
        Tenant.objects.all().delete()

        self.tenant = Tenant.objects.create(
            name="Salão Teste", slug="salao-teste", plan_tier="pro", is_active=True
        )

        self.client_user = CustomUser.objects.create_user(
            username="cliente_teste",
            email="cliente@teste.com",
            password="senha123",
            tenant=self.tenant,
            phone_number="+351912345678",
        )

        self.salon_user = CustomUser.objects.create_user(
            username="salao_teste",
            email="salao@teste.com",
            password="senha123",
            tenant=self.tenant,
        )

        # Dois serviços
        self.service1 = Service.objects.create(
            name="Corte",
            price_eur=20.00,
            duration_minutes=45,
            user=self.salon_user,
            tenant=self.tenant,
        )
        self.service2 = Service.objects.create(
            name="Coloração",
            price_eur=35.00,
            duration_minutes=60,
            user=self.salon_user,
            tenant=self.tenant,
        )

        # Dois profissionais
        self.prof1 = Professional.objects.create(
            name="Ana",
            bio="Expert corte",
            user=self.salon_user,
            tenant=self.tenant,
        )
        self.prof2 = Professional.objects.create(
            name="Bruno",
            bio="Expert cor",
            user=self.salon_user,
            tenant=self.tenant,
        )

        # Mapear ofertas de serviços
        ProfessionalService.objects.create(
            tenant=self.tenant,
            professional=self.prof1,
            service=self.service1,
            is_active=True,
        )
        ProfessionalService.objects.create(
            tenant=self.tenant,
            professional=self.prof2,
            service=self.service2,
            is_active=True,
        )

        # Criar slots para cada profissional
        base = timezone.now() + timedelta(days=1, hours=9)
        self.slot_p1_a = ScheduleSlot.objects.create(
            professional=self.prof1,
            start_time=base,
            end_time=base + timedelta(minutes=45),
            is_available=True,
            tenant=self.tenant,
        )
        self.slot_p1_b = ScheduleSlot.objects.create(
            professional=self.prof1,
            start_time=base + timedelta(days=1),
            end_time=base + timedelta(days=1, minutes=45),
            is_available=True,
            tenant=self.tenant,
        )
        self.slot_p2_a = ScheduleSlot.objects.create(
            professional=self.prof2,
            start_time=base + timedelta(hours=1),
            end_time=base + timedelta(hours=2),
            is_available=True,
            tenant=self.tenant,
        )

        self.client_api = APIClient()
        self.client_api.force_authenticate(user=self.client_user)

        self.url = reverse("appointment-mixed-bulk-create")

    def test_mixed_bulk_success_201(self):
        """Cria múltiplos agendamentos com serviços e profissionais variados."""
        data = {
            "items": [
                {
                    "slot_id": self.slot_p1_a.id,
                    "service_id": self.service1.id,
                    "professional_id": self.prof1.id,
                    "notes": "Corte",
                },
                {
                    "slot_id": self.slot_p2_a.id,
                    "service_id": self.service2.id,
                    "professional_id": self.prof2.id,
                    "notes": "Cor",
                },
            ]
        }

        resp = self.client_api.post(self.url, data, format="json")
        assert resp.status_code == status.HTTP_201_CREATED
        body = resp.json()
        assert body["success"] is True
        assert body["appointments_created"] == 2
        assert len(body["appointment_ids"]) == 2
        # total_value = 20 + 35
        assert body["total_value"] == 55.0
        assert all(r["status"] == "created" for r in body["results"])  # ambos criados

        # banco
        assert Appointment.objects.count() == 2

    def test_mixed_bulk_partial_207(self):
        """Sucesso parcial: um item inválido deve retornar erro no resultado."""
        # tornar um slot indisponível
        self.slot_p1_a.mark_booked()

        data = {
            "items": [
                {
                    "slot_id": self.slot_p1_a.id,  # indisponível
                    "service_id": self.service1.id,
                    "professional_id": self.prof1.id,
                },
                {
                    "slot_id": self.slot_p2_a.id,
                    "service_id": self.service2.id,
                    "professional_id": self.prof2.id,
                },
            ]
        }

        resp = self.client_api.post(self.url, data, format="json")
        assert resp.status_code == 207
        body = resp.json()
        assert body["appointments_created"] == 1
        # primeiro item erro, segundo criado
        assert body["results"][0]["status"] == "error"
        assert body["results"][1]["status"] == "created"

    def test_mixed_bulk_none_created_400(self):
        """Nenhum criado: todos os itens inválidos leva a 400."""
        # profissional errado para slot
        data = {
            "items": [
                {
                    "slot_id": self.slot_p1_a.id,
                    "service_id": self.service1.id,
                    "professional_id": self.prof2.id,  # não é dono do slot
                },
                {
                    "slot_id": self.slot_p1_b.id,
                    "service_id": self.service2.id,  # serviço não oferecido por prof1
                    "professional_id": self.prof1.id,
                },
            ]
        }

        resp = self.client_api.post(self.url, data, format="json")
        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        body = resp.json()
        assert body["appointments_created"] == 0
        assert all(r["status"] == "error" for r in body["results"])

    def test_mixed_bulk_validation_duplicates_400(self):
        """Validação do serializer: slots duplicados devem resultar em 400."""
        data = {
            "items": [
                {
                    "slot_id": self.slot_p1_a.id,
                    "service_id": self.service1.id,
                    "professional_id": self.prof1.id,
                },
                {
                    "slot_id": self.slot_p1_a.id,  # duplicado
                    "service_id": self.service1.id,
                    "professional_id": self.prof1.id,
                },
            ]
        }
        resp = self.client_api.post(self.url, data, format="json")
        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert "Slots duplicados" in str(resp.json())

    def test_mixed_bulk_long_service_reserves_contiguous_block(self):
        """Reserva bloco contíguo e cria vínculos de slots extras para serviço longo."""
        # Criar serviço longo (90 min) para prof1
        long_service = Service.objects.create(
            name="Alisamento",
            price_eur=80.00,
            duration_minutes=90,
            user=self.salon_user,
            tenant=self.tenant,
        )
        ProfessionalService.objects.create(
            tenant=self.tenant,
            professional=self.prof1,
            service=long_service,
            is_active=True,
        )

        # Criar dois slots contíguos de 45min no mesmo dia para prof1
        base = timezone.now() + timedelta(days=2, hours=9)
        s1 = ScheduleSlot.objects.create(
            professional=self.prof1,
            start_time=base,
            end_time=base + timedelta(minutes=45),
            is_available=True,
            tenant=self.tenant,
        )
        s2 = ScheduleSlot.objects.create(
            professional=self.prof1,
            start_time=base + timedelta(minutes=45),
            end_time=base + timedelta(minutes=90),
            is_available=True,
            tenant=self.tenant,
        )

        data = {
            "items": [
                {
                    "slot_id": s1.id,
                    "service_id": long_service.id,
                    "professional_id": self.prof1.id,
                    "notes": "Serviço longo",
                }
            ]
        }

        resp = self.client_api.post(self.url, data, format="json")
        assert resp.status_code in (status.HTTP_201_CREATED, 207)
        body = resp.json()
        # Deve criar 1 agendamento
        assert body["appointments_created"] == 1
        appt_id = body["appointment_ids"][0]

        # Banco: slots contíguos devem estar reservados
        s1.refresh_from_db()
        s2.refresh_from_db()
        assert s1.is_available is False and s1.status == "booked"
        assert s2.is_available is False and s2.status == "booked"

        # Deve existir vínculo de slot extra
        appt = Appointment.objects.get(id=appt_id)
        extras = AppointmentReservedSlot.objects.filter(appointment=appt)
        assert extras.count() == 1
        assert extras.first().slot_id == s2.id
