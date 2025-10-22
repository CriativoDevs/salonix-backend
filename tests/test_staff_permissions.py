from datetime import timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from core.models import (
    Appointment,
    AppointmentSeries,
    Professional,
    ScheduleSlot,
    Service,
)
from users.models import CustomUser, Tenant, TenantStaffMember


class TestStaffPermissions(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.get(slug="test-default")

        self.owner = CustomUser.objects.create_user(
            username="owner",
            email="owner@test.com",
            password="pass123",
            tenant=self.tenant,
        )
        self.manager = CustomUser.objects.create_user(
            username="manager",
            email="manager@test.com",
            password="pass123",
            tenant=self.tenant,
        )
        self.collaborator = CustomUser.objects.create_user(
            username="collab",
            email="collab@test.com",
            password="pass123",
            tenant=self.tenant,
        )
        self.other_collaborator = CustomUser.objects.create_user(
            username="collab2",
            email="collab2@test.com",
            password="pass123",
            tenant=self.tenant,
        )
        self.client_user = CustomUser.objects.create_user(
            username="client",
            email="client@test.com",
            password="pass123",
            tenant=self.tenant,
        )

        self.owner_staff = TenantStaffMember.objects.create(
            tenant=self.tenant,
            user=self.owner,
            role=TenantStaffMember.Role.OWNER,
            status=TenantStaffMember.Status.ACTIVE,
        )
        self.manager_staff = TenantStaffMember.objects.create(
            tenant=self.tenant,
            user=self.manager,
            role=TenantStaffMember.Role.MANAGER,
            status=TenantStaffMember.Status.ACTIVE,
        )
        self.collab_staff = TenantStaffMember.objects.create(
            tenant=self.tenant,
            user=self.collaborator,
            role=TenantStaffMember.Role.COLLABORATOR,
            status=TenantStaffMember.Status.ACTIVE,
        )
        self.other_collab_staff = TenantStaffMember.objects.create(
            tenant=self.tenant,
            user=self.other_collaborator,
            role=TenantStaffMember.Role.COLLABORATOR,
            status=TenantStaffMember.Status.ACTIVE,
        )

        self.service = Service.objects.create(
            name="Corte VIP",
            price_eur=50,
            duration_minutes=60,
            user=self.owner,
            tenant=self.tenant,
        )
        self.professional = Professional.objects.create(
            name="Pro 1",
            user=self.collaborator,
            staff_member=self.collab_staff,
            tenant=self.tenant,
        )
        self.other_professional = Professional.objects.create(
            name="Pro 2",
            user=self.manager,
            staff_member=self.manager_staff,
            tenant=self.tenant,
        )

        start_time = timezone.now() + timedelta(hours=1)
        self.slot = ScheduleSlot.objects.create(
            professional=self.professional,
            start_time=start_time,
            end_time=start_time + timedelta(hours=1),
            is_available=False,
            tenant=self.tenant,
        )
        self.slot.status = "booked"
        self.slot.save(update_fields=["status"])

        self.appointment = Appointment.objects.create(
            tenant=self.tenant,
            client=self.client_user,
            service=self.service,
            professional=self.professional,
            slot=self.slot,
            status="scheduled",
        )

        series_slot_start = timezone.now() + timedelta(days=1)
        self.series_slot = ScheduleSlot.objects.create(
            professional=self.professional,
            start_time=series_slot_start,
            end_time=series_slot_start + timedelta(hours=1),
            is_available=False,
            tenant=self.tenant,
        )
        self.series_slot.status = "booked"
        self.series_slot.save(update_fields=["status"])

        self.series = AppointmentSeries.objects.create(
            tenant=self.tenant,
            client=self.client_user,
            service=self.service,
            professional=self.professional,
            notes="",
        )
        Appointment.objects.create(
            tenant=self.tenant,
            client=self.client_user,
            service=self.service,
            professional=self.professional,
            slot=self.series_slot,
            status="scheduled",
            series=self.series,
        )

        other_slot_start = timezone.now() + timedelta(days=2)
        self.other_slot = ScheduleSlot.objects.create(
            professional=self.other_professional,
            start_time=other_slot_start,
            end_time=other_slot_start + timedelta(hours=1),
            is_available=True,
            tenant=self.tenant,
        )

        self.collab_available_slot = ScheduleSlot.objects.create(
            professional=self.professional,
            start_time=timezone.now() + timedelta(days=3),
            end_time=timezone.now() + timedelta(days=3, hours=1),
            is_available=True,
            tenant=self.tenant,
        )

        self.owner_client = APIClient()
        self.owner_client.force_authenticate(user=self.owner)
        self.manager_client = APIClient()
        self.manager_client.force_authenticate(user=self.manager)
        self.collab_client = APIClient()
        self.collab_client.force_authenticate(user=self.collaborator)
        self.other_collab_client = APIClient()
        self.other_collab_client.force_authenticate(user=self.other_collaborator)

    def test_owner_can_retrieve_appointment_detail(self):
        url = reverse("appointment-detail", kwargs={"pk": self.appointment.id})
        response = self.owner_client.get(url)
        assert response.status_code == status.HTTP_200_OK
        assert response.data["id"] == self.appointment.id

    def test_manager_can_retrieve_appointment_detail(self):
        url = reverse("appointment-detail", kwargs={"pk": self.appointment.id})
        response = self.manager_client.get(url)
        assert response.status_code == status.HTTP_200_OK
        assert response.data["id"] == self.appointment.id

    def test_collaborator_cannot_retrieve_appointment_detail_of_other_staff(self):
        url = reverse("appointment-detail", kwargs={"pk": self.appointment.id})
        response = self.other_collab_client.get(url)
        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_owner_can_download_ics_for_staff_appointment(self):
        url = reverse("appointment-ics-download", kwargs={"pk": self.appointment.id})
        response = self.owner_client.get(url)
        assert response.status_code == status.HTTP_200_OK
        assert response["Content-Type"] == "text/calendar; charset=utf-8"

    def test_collaborator_forbidden_to_download_ics_for_other_staff(self):
        url = reverse("appointment-ics-download", kwargs={"pk": self.appointment.id})
        response = self.other_collab_client.get(url)
        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_owner_can_view_series_from_collaborator(self):
        url = reverse("appointment-series-detail", kwargs={"pk": self.series.id})
        response = self.owner_client.get(url)
        assert response.status_code == status.HTTP_200_OK
        assert response.data["id"] == self.series.id

    def test_collaborator_cannot_view_series_from_other_staff(self):
        url = reverse("appointment-series-detail", kwargs={"pk": self.series.id})
        response = self.other_collab_client.get(url)
        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_collaborator_cannot_create_series_for_other_professional(self):
        url = reverse("appointment-series-create")
        payload = {
            "service_id": self.service.id,
            "professional_id": self.other_professional.id,
            "appointments": [{"slot_id": self.other_slot.id}],
        }
        response = self.collab_client.post(url, payload, format="json")
        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_collaborator_can_create_series_for_self(self):
        url = reverse("appointment-series-create")
        payload = {
            "service_id": self.service.id,
            "professional_id": self.professional.id,
            "appointments": [{"slot_id": self.collab_available_slot.id}],
            "notes": "Sessão exclusiva",
        }
        response = self.collab_client.post(url, payload, format="json")
        assert response.status_code == status.HTTP_201_CREATED
        data = response.json()
        assert data["success"] is True
        assert data["professional_name"] == self.professional.name

    def test_collaborator_cannot_create_bulk_for_other_professional(self):
        url = reverse("appointment-bulk-create")
        payload = {
            "service_id": self.service.id,
            "professional_id": self.other_professional.id,
            "appointments": [{"slot_id": self.other_slot.id}],
        }
        response = self.collab_client.post(url, payload, format="json")
        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_collaborator_can_create_bulk_for_self(self):
        url = reverse("appointment-bulk-create")
        payload = {
            "service_id": self.service.id,
            "professional_id": self.professional.id,
            "appointments": [{"slot_id": self.collab_available_slot.id}],
        }
        response = self.collab_client.post(url, payload, format="json")
        assert response.status_code == status.HTTP_201_CREATED
        data = response.json()
        assert data["success"] is True
        assert data["appointments_created"] == 1
