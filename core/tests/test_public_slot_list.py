import pytest
from datetime import timedelta
from django.utils import timezone
from rest_framework.test import APIClient

from django.contrib.auth import get_user_model

from users.models import Tenant
from core.models import Professional, ScheduleSlot

User = get_user_model()


@pytest.mark.django_db
class TestPublicSlotListView:
    def setup_method(self):
        self.client = APIClient()
        self.tenant = Tenant.objects.create(
            name="Salão Teste",
            slug="salao-teste",
            plan_tier=Tenant.PLAN_BASIC,
            pwa_client_enabled=True,
            is_active=True,
        )
        self.owner = User.objects.create_user(
            username="owner-salao-teste",
            email="owner@salao-teste.local",
            password="senha-teste-123",
            tenant=self.tenant,
        )
        self.professional = Professional.objects.create(
            tenant=self.tenant, user=self.owner, name="Alice"
        )
        self.url = "/api/public/slots/"

    def test_past_slots_are_not_returned(self):
        now = timezone.now()
        ScheduleSlot.objects.create(
            tenant=self.tenant,
            professional=self.professional,
            start_time=now - timedelta(days=30),
            end_time=now - timedelta(days=30) + timedelta(minutes=30),
            is_available=True,
        )
        future_slot = ScheduleSlot.objects.create(
            tenant=self.tenant,
            professional=self.professional,
            start_time=now + timedelta(days=1),
            end_time=now + timedelta(days=1) + timedelta(minutes=30),
            is_available=True,
        )

        response = self.client.get(
            self.url,
            {"professional_id": self.professional.id, "tenant": self.tenant.slug},
        )

        assert response.status_code == 200
        returned_ids = [slot["id"] for slot in response.data]
        assert returned_ids == [future_slot.id]
