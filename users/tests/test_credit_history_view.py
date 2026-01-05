import pytest
from decimal import Decimal
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient
from users.models import Tenant, CommLedger, CustomUser
from django.utils import timezone
import datetime


@pytest.mark.django_db
class TestCreditHistoryView:
    def setup_method(self):
        self.client = APIClient()
        self.url = "/api/users/credits/history/"

        self.tenant = Tenant.objects.create(
            name="Test Tenant", slug="test-tenant", plan_tier="scale"
        )
        self.user = CustomUser.objects.create_user(
            username="user@test.com",
            email="user@test.com",
            password="password",
            tenant=self.tenant,
        )
        self.client.force_authenticate(user=self.user)

        # Create some transactions
        base_time = timezone.now()

        # Transaction 1: Today
        self.p1 = CommLedger.objects.create(
            tenant=self.tenant,
            transaction_type="purchase",
            amount_eur=Decimal("10.00"),
            balance_before=Decimal("0.00"),
            balance_after=Decimal("10.00"),
            status="completed",
            description="Purchase 1",
            created_at=base_time,
        )

        # Transaction 2: Yesterday
        self.c1 = CommLedger.objects.create(
            tenant=self.tenant,
            transaction_type="consumption",
            amount_eur=Decimal("5.00"),
            balance_before=Decimal("10.00"),
            balance_after=Decimal("5.00"),
            status="completed",
            description="Consumption 1",
        )
        # Hack to set created_at in the past (since auto_now_add=True)
        CommLedger.objects.filter(pk=self.c1.pk).update(
            created_at=base_time - datetime.timedelta(days=1)
        )

    def test_list_history(self):
        response = self.client.get(self.url)
        assert response.status_code == status.HTTP_200_OK
        assert len(response.data["results"]) == 2

    def test_filter_by_date(self):
        today = timezone.now().date().isoformat()

        # Filter for today only
        response = self.client.get(f"{self.url}?start_date={today}&end_date={today}")
        assert response.status_code == status.HTTP_200_OK
        assert len(response.data["results"]) == 1
        assert response.data["results"][0]["description"] == "Purchase 1"

    def test_filter_by_type(self):
        response = self.client.get(f"{self.url}?transaction_type=consumption")
        assert response.status_code == status.HTTP_200_OK
        assert len(response.data["results"]) == 1
        assert response.data["results"][0]["transaction_type"] == "consumption"
