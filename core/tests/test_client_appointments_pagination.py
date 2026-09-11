import pytest
from datetime import timedelta
from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from users.models import Tenant
from core.models import Professional, Service, ScheduleSlot, Appointment, SalonCustomer

User = get_user_model()


@pytest.mark.django_db
class TestClientAppointmentsPagination:
    def setup_method(self):
        self.tenant = Tenant.objects.create(
            name="Salão Paginação",
            slug="salao-paginacao",
            plan_tier=Tenant.PLAN_BASIC,
            pwa_client_enabled=True,
        )
        self.owner = User.objects.create_user(
            username="owner-paginacao",
            email="owner@salao-paginacao.local",
            password="senha-teste-123",
            tenant=self.tenant,
        )
        self.professional = Professional.objects.create(
            tenant=self.tenant, user=self.owner, name="Alice"
        )
        self.service = Service.objects.create(
            tenant=self.tenant,
            user=self.owner,
            name="Corte",
            duration_minutes=30,
            price_eur="20.00",
        )
        self.customer = SalonCustomer.objects.create(
            tenant=self.tenant,
            name="Cliente Paginação",
            email="cliente-paginacao@test.com",
        )
        self.customer.set_password("securepass123")
        self.customer.save()

        self.client = APIClient()
        login_response = self.client.post(
            reverse("clients_login"),
            {
                "email": "cliente-paginacao@test.com",
                "password": "securepass123",
                "tenant_slug": self.tenant.slug,
            },
            format="json",
        )
        assert login_response.status_code == status.HTTP_200_OK
        self.access_token = login_response.data["access"]

    def _auth_headers(self):
        return {"HTTP_AUTHORIZATION": f"Bearer {self.access_token}"}

    def _create_appointment(self, start_offset, status_value):
        now = timezone.now()
        start = now + start_offset
        slot = ScheduleSlot.objects.create(
            tenant=self.tenant,
            professional=self.professional,
            start_time=start,
            end_time=start + timedelta(minutes=30),
            is_available=False,
        )
        return Appointment.objects.create(
            tenant=self.tenant,
            client=self.owner,
            customer=self.customer,
            service=self.service,
            professional=self.professional,
            slot=slot,
            status=status_value,
        )

    def test_upcoming_paginates_with_default_limit(self):
        for i in range(25):
            self._create_appointment(timedelta(days=i + 1), "scheduled")

        response = self.client.get(
            "/api/clients/me/appointments/upcoming/", **self._auth_headers()
        )

        assert response.status_code == status.HTTP_200_OK
        assert len(response.data["results"]) == 20
        assert response.data["has_more"] is True

    def test_upcoming_second_page_has_remainder(self):
        for i in range(25):
            self._create_appointment(timedelta(days=i + 1), "scheduled")

        response = self.client.get(
            "/api/clients/me/appointments/upcoming/",
            {"limit": 20, "offset": 20},
            **self._auth_headers(),
        )

        assert response.status_code == status.HTTP_200_OK
        assert len(response.data["results"]) == 5
        assert response.data["has_more"] is False

    def test_upcoming_respects_custom_limit(self):
        for i in range(5):
            self._create_appointment(timedelta(days=i + 1), "scheduled")

        response = self.client.get(
            "/api/clients/me/appointments/upcoming/",
            {"limit": 2},
            **self._auth_headers(),
        )

        assert response.status_code == status.HTTP_200_OK
        assert len(response.data["results"]) == 2
        assert response.data["has_more"] is True

    def test_upcoming_limit_is_capped_at_100(self):
        response = self.client.get(
            "/api/clients/me/appointments/upcoming/",
            {"limit": 9999},
            **self._auth_headers(),
        )

        assert response.status_code == status.HTTP_200_OK
        assert response.data["has_more"] is False

    def test_history_paginates_with_default_limit(self):
        for i in range(25):
            self._create_appointment(-timedelta(days=i + 1), "completed")

        response = self.client.get(
            "/api/clients/me/appointments/history/", **self._auth_headers()
        )

        assert response.status_code == status.HTTP_200_OK
        assert len(response.data["results"]) == 20
        assert response.data["has_more"] is True

    def test_no_results_returns_empty_with_has_more_false(self):
        response = self.client.get(
            "/api/clients/me/appointments/upcoming/", **self._auth_headers()
        )

        assert response.status_code == status.HTTP_200_OK
        assert response.data["results"] == []
        assert response.data["has_more"] is False
