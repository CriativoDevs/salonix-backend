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


class TestMixedBulkStartEndTime(TestCase):
    """Testes para mixed-bulk usando start_time/end_time (sem slot_id) e mix dos dois."""

    def setUp(self):
        Tenant.objects.all().delete()

        self.tenant = Tenant.objects.create(
            name="Salão MX", slug="salao-mx", plan_tier="pro", is_active=True
        )
        self.salon_user = CustomUser.objects.create_user(
            username="salon_mx", email="salon@mx.com", password="x", tenant=self.tenant
        )
        self.client_user = CustomUser.objects.create_user(
            username="client_mx",
            email="client@mx.com",
            password="x",
            tenant=self.tenant,
            phone_number="+351912345678",
        )
        self.service = Service.objects.create(
            name="Corte",
            price_eur=20.00,
            duration_minutes=30,
            user=self.salon_user,
            tenant=self.tenant,
        )
        self.prof = Professional.objects.create(
            name="Carlos", bio="", user=self.salon_user, tenant=self.tenant
        )
        ProfessionalService.objects.create(
            tenant=self.tenant,
            professional=self.prof,
            service=self.service,
            is_active=True,
        )

        self.api = APIClient()
        self.api.force_authenticate(user=self.client_user)
        self.url = reverse("appointment-mixed-bulk-create")

    def _st(self, days=1, hour=10):
        base = timezone.now().replace(minute=0, second=0, microsecond=0)
        return base + timedelta(days=days, hours=hour)

    # ------------------------------------------------------------------
    # 1. Mixed-bulk totalmente com start_time/end_time
    # ------------------------------------------------------------------

    def test_all_start_end_time_creates_slots_and_appointments(self):
        st1 = self._st(days=1, hour=10)
        st2 = self._st(days=2, hour=14)

        data = {
            "items": [
                {
                    "start_time": st1.isoformat(),
                    "end_time": (st1 + timedelta(hours=1)).isoformat(),
                    "service_id": self.service.id,
                    "professional_id": self.prof.id,
                },
                {
                    "start_time": st2.isoformat(),
                    "end_time": (st2 + timedelta(hours=1)).isoformat(),
                    "service_id": self.service.id,
                    "professional_id": self.prof.id,
                },
            ]
        }

        resp = self.api.post(self.url, data, format="json")
        assert resp.status_code == status.HTTP_201_CREATED, resp.json()

        body = resp.json()
        assert body["appointments_created"] == 2
        assert all(r["status"] == "created" for r in body["results"])

        # Slots foram criados e estão booked
        assert ScheduleSlot.objects.filter(
            professional=self.prof, tenant=self.tenant, status="booked"
        ).count() == 2

    # ------------------------------------------------------------------
    # 2. Mixed-bulk misto: slot_id + start_time/end_time
    # ------------------------------------------------------------------

    def test_mixed_slot_id_and_start_end_time(self):
        existing_slot = ScheduleSlot.objects.create(
            professional=self.prof,
            start_time=self._st(days=3, hour=9),
            end_time=self._st(days=3, hour=9) + timedelta(hours=1),
            is_available=True,
            tenant=self.tenant,
        )
        auto_st = self._st(days=4, hour=14)

        data = {
            "items": [
                {
                    "slot_id": existing_slot.id,
                    "service_id": self.service.id,
                    "professional_id": self.prof.id,
                },
                {
                    "start_time": auto_st.isoformat(),
                    "end_time": (auto_st + timedelta(hours=1)).isoformat(),
                    "service_id": self.service.id,
                    "professional_id": self.prof.id,
                },
            ]
        }

        resp = self.api.post(self.url, data, format="json")
        assert resp.status_code == status.HTTP_201_CREATED, resp.json()

        body = resp.json()
        assert body["appointments_created"] == 2
        assert all(r["status"] == "created" for r in body["results"])

        existing_slot.refresh_from_db()
        assert existing_slot.status == "booked"

    # ------------------------------------------------------------------
    # 3. Validação: campos obrigatórios para itens sem slot_id
    # ------------------------------------------------------------------

    def test_missing_start_time_returns_400(self):
        st = self._st(days=5, hour=10)
        data = {
            "items": [
                {
                    "end_time": (st + timedelta(hours=1)).isoformat(),
                    "service_id": self.service.id,
                    "professional_id": self.prof.id,
                }
            ]
        }
        resp = self.api.post(self.url, data, format="json")
        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert "start_time" in str(resp.json())

    def test_past_start_time_returns_400(self):
        past = timezone.now() - timedelta(hours=2)
        data = {
            "items": [
                {
                    "start_time": past.isoformat(),
                    "end_time": (past + timedelta(hours=1)).isoformat(),
                    "service_id": self.service.id,
                    "professional_id": self.prof.id,
                }
            ]
        }
        resp = self.api.post(self.url, data, format="json")
        assert resp.status_code == status.HTTP_400_BAD_REQUEST

    # ------------------------------------------------------------------
    # 4. Sucesso parcial: item com start_time inválido não cancela os demais
    #    (mixed-bulk mantém comportamento de sucesso parcial)
    # ------------------------------------------------------------------

    def test_partial_success_one_auto_item_fails_other_succeeds(self):
        """
        Mixed-bulk tem sucesso parcial: se um item (slot_id) falha,
        o outro (start_time/end_time) ainda pode ser criado.
        """
        # Slot indisponível para forçar erro no primeiro item
        bad_slot = ScheduleSlot.objects.create(
            professional=self.prof,
            start_time=self._st(days=6, hour=9),
            end_time=self._st(days=6, hour=9) + timedelta(hours=1),
            is_available=False,
            status="booked",
            tenant=self.tenant,
        )
        auto_st = self._st(days=7, hour=14)

        data = {
            "items": [
                {
                    "slot_id": bad_slot.id,  # indisponível
                    "service_id": self.service.id,
                    "professional_id": self.prof.id,
                },
                {
                    "start_time": auto_st.isoformat(),
                    "end_time": (auto_st + timedelta(hours=1)).isoformat(),
                    "service_id": self.service.id,
                    "professional_id": self.prof.id,
                },
            ]
        }

        resp = self.api.post(self.url, data, format="json")
        assert resp.status_code == 207  # sucesso parcial

        body = resp.json()
        assert body["appointments_created"] == 1
        assert body["results"][0]["status"] == "error"
        assert body["results"][1]["status"] == "created"

        # Slot auto-criado está booked
        assert ScheduleSlot.objects.filter(
            professional=self.prof, start_time=auto_st, status="booked"
        ).exists()

    # ------------------------------------------------------------------
    # 5. Profissional não oferece serviço no caminho auto-create
    # ------------------------------------------------------------------

    def test_auto_create_professional_not_offering_service_returns_error(self):
        other_service = Service.objects.create(
            name="Massagem",
            price_eur=50.00,
            duration_minutes=60,
            user=self.salon_user,
            tenant=self.tenant,
        )
        # Não criar ProfessionalService para this.prof + other_service
        auto_st = self._st(days=8, hour=10)

        data = {
            "items": [
                {
                    "start_time": auto_st.isoformat(),
                    "end_time": (auto_st + timedelta(hours=1)).isoformat(),
                    "service_id": other_service.id,
                    "professional_id": self.prof.id,
                }
            ]
        }

        resp = self.api.post(self.url, data, format="json")
        # Nenhum criado → 400
        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        body = resp.json()
        assert body["results"][0]["status"] == "error"
        assert "oferece" in body["results"][0]["message"].lower()
