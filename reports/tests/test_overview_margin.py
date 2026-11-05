import pytest
from decimal import Decimal
from django.core.cache import cache
from django.utils import timezone
from datetime import timedelta
from rest_framework.test import APIClient

from inventory.models import InventoryItem, StockMovement
from core.models import Appointment
from users.models import UserFeatureFlags


@pytest.fixture(autouse=True)
def clear_cache():
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def api_client():
    return APIClient()


@pytest.fixture
def authed_client(api_client, user_fixture):
    ff, _ = UserFeatureFlags.objects.get_or_create(user=user_fixture)
    ff.reports_enabled = True
    ff.save(update_fields=["reports_enabled"])
    api_client.force_authenticate(user=user_fixture)
    return api_client


URL = "/api/reports/overview/"


@pytest.mark.django_db
class TestOverviewMargin:
    def test_overview_without_stock_has_no_margin_fields(self, authed_client):
        response = authed_client.get(URL)
        assert response.status_code == 200
        data = response.json()
        assert data["stock_active"] is False
        assert data["product_cost_total"] is None
        assert data["margin_total"] is None
        # campos já existentes continuam presentes (contrato estável)
        assert "revenue_total" in data
        assert "appointments_total" in data

    def test_overview_with_stock_computes_margin(
        self, authed_client, tenant_fixture, service_fixture, professional_fixture
    ):
        from core.models import ScheduleSlot
        from django.contrib.auth import get_user_model

        ClientUser = get_user_model()
        slot = ScheduleSlot.objects.create(
            tenant=tenant_fixture,
            professional=professional_fixture,
            start_time=timezone.now() - timedelta(hours=2),
            end_time=timezone.now() - timedelta(hours=1),
            is_available=False,
        )
        client_user = ClientUser.objects.create_user(
            username="client-margin-test",
            email="client-margin-test@example.com",
            password="testpass123",
        )
        Appointment.objects.create(
            tenant=tenant_fixture,
            client=client_user,
            service=service_fixture,
            professional=professional_fixture,
            slot=slot,
            status="completed",
        )

        item = InventoryItem.objects.create(
            tenant=tenant_fixture,
            name="Tinta",
            unit="frasco",
            quantity=100,
            unit_cost=Decimal("3.00"),
        )
        StockMovement.objects.create(
            tenant=tenant_fixture,
            item=item,
            movement_type=StockMovement.MovementType.OUT,
            quantity=4,
        )

        response = authed_client.get(URL)
        assert response.status_code == 200
        data = response.json()
        assert data["stock_active"] is True
        # 4 * 3.00 = 12.00 de custo de produto
        assert float(data["product_cost_total"]) == 12.00
        expected_margin = float(data["revenue_total"]) - 12.00
        assert float(data["margin_total"]) == pytest.approx(expected_margin)
