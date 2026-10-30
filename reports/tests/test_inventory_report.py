import pytest
from decimal import Decimal
from rest_framework.test import APIClient

from inventory.models import InventoryItem, StockMovement
from users.models import UserFeatureFlags


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


URL = "/api/reports/inventory/"


@pytest.mark.django_db
class TestInventoryReportView:
    def test_requires_auth(self, api_client):
        response = api_client.get(URL)
        assert response.status_code == 401

    def test_tenant_without_items_gets_empty_inactive_report(self, authed_client):
        response = authed_client.get(URL)
        assert response.status_code == 200
        data = response.json()
        assert data["stock_active"] is False
        assert (
            data["total_stock_value"] == "0.00"
            or float(data["total_stock_value"]) == 0.0
        )
        assert data["low_stock_items_count"] == 0
        assert data["low_stock_items"] == []
        assert data["turnover"] == []

    def test_tenant_with_items_sees_total_value_and_low_stock(
        self, authed_client, tenant_fixture
    ):
        InventoryItem.objects.create(
            tenant=tenant_fixture,
            name="Luvas",
            unit="cx",
            quantity=10,
            minimum_quantity=5,
            unit_cost=Decimal("2.00"),
        )
        InventoryItem.objects.create(
            tenant=tenant_fixture,
            name="Agulhas",
            unit="unidade",
            quantity=2,
            minimum_quantity=5,
            unit_cost=Decimal("1.50"),
        )

        response = authed_client.get(URL)
        assert response.status_code == 200
        data = response.json()
        assert data["stock_active"] is True
        # 10 * 2.00 + 2 * 1.50 = 23.00
        assert float(data["total_stock_value"]) == 23.00
        assert data["low_stock_items_count"] == 1
        assert data["low_stock_items"][0]["name"] == "Agulhas"

    def test_turnover_counts_out_movements_in_period(
        self, authed_client, tenant_fixture
    ):
        item = InventoryItem.objects.create(
            tenant=tenant_fixture,
            name="Tinta",
            unit="frasco",
            quantity=20,
            unit_cost=Decimal("5.00"),
        )
        StockMovement.objects.create(
            tenant=tenant_fixture,
            item=item,
            movement_type=StockMovement.MovementType.OUT,
            quantity=8,
        )
        StockMovement.objects.create(
            tenant=tenant_fixture,
            item=item,
            movement_type=StockMovement.MovementType.IN,
            quantity=50,
        )

        response = authed_client.get(URL)
        assert response.status_code == 200
        data = response.json()
        turnover_row = next(r for r in data["turnover"] if r["item_id"] == item.id)
        assert turnover_row["quantity_out"] == 8
        # 8 saídas / (20 atual, após +50 -8 = 62 na verdade) -- valida apenas
        # que current_quantity reflete o saldo real do item após os movimentos
        item.refresh_from_db()
        assert turnover_row["current_quantity"] == item.quantity

    def test_other_tenant_items_are_not_leaked(self, authed_client, tenant_fixture):
        from users.models import Tenant

        other_tenant = Tenant.objects.create(
            slug="tenant-b-inv-report",
            name="Tenant B Inv Report",
            plan_tier=Tenant.PLAN_BASIC,
        )
        InventoryItem.objects.create(
            tenant=other_tenant,
            name="Item do outro tenant",
            unit="unidade",
            quantity=1,
            minimum_quantity=10,
            unit_cost=Decimal("100.00"),
        )

        response = authed_client.get(URL)
        assert response.status_code == 200
        data = response.json()
        # tenant_fixture não tem itens próprios -> estoque inativo, mesmo que
        # outro tenant tenha itens
        assert data["stock_active"] is False
