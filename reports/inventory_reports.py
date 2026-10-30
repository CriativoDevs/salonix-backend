"""Relatórios de estoque e cruzamento com faturamento (BE-REPORTS-01, #569).

Dois pontos de entrada:
- `get_stock_report_data`: relatório de estoque isolado (valor total em
  stock, giro/turnover por item, itens em alerta de estoque baixo).
  Independente de qualquer venda/booking.
- `get_cogs_and_margin`: COGS (Cost of Goods Sold / custo das mercadorias
  vendidas — aqui, custo do produto de estoque consumido) e margem
  (receita - COGS) para um período, para somar ao relatório de faturamento
  existente (`OverviewReportView`).

Gate: ambos dependem de `inventory.services.tenant_has_active_stock`, que
reaproveita o único sinal real de "estoque ativo" existente hoje no projeto
(ver docstring desse helper) — `inventory` não tem gate de plano.

Cálculos:
- `total_stock_value` = soma de `quantity * unit_cost` de cada item do
  tenant (valoração ao custo, sem markup).
- `turnover_rate` por item = quantidade saída (`StockMovement` tipo `out`)
  no período / quantidade atual do item. Proxy simples de giro de estoque;
  fica `None` quando a quantidade atual é zero (divisão indefinida).
- `product_cost_total` (COGS) = soma de `quantity * item.unit_cost` de
  todas as saídas (`StockMovement` tipo `out`) do tenant no período,
  usando `StockMovement.created_at` como data de referência. Não há hoje
  nenhuma ligação entre `StockMovement`/`InventoryItem` e
  `Appointment`/`Service`, então o COGS é calculado no nível do tenant
  (todo consumo de estoque no período), não por serviço/venda individual.
- `margin_total` = `revenue_total - product_cost_total`.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Optional

from django.db.models import F, Sum

from inventory.models import InventoryItem, StockMovement
from inventory.services import tenant_has_active_stock


def _empty_stock_report() -> dict:
    return {
        "stock_active": False,
        "total_stock_value": Decimal("0.00"),
        "low_stock_items_count": 0,
        "low_stock_items": [],
        "turnover": [],
    }


def get_stock_report_data(tenant, start_dt=None, end_dt=None) -> dict:
    """Relatório de estoque isolado para o tenant.

    `start_dt`/`end_dt` delimitam apenas a janela usada para calcular o giro
    (saídas no período); valor total e itens em alerta refletem o estado
    atual do estoque (não dependem de período).
    """
    if not tenant_has_active_stock(tenant):
        return _empty_stock_report()

    items = list(InventoryItem.objects.filter(tenant=tenant))

    total_stock_value = sum(
        (item.unit_cost or Decimal("0")) * item.quantity for item in items
    ) or Decimal("0.00")

    low_stock_items = [
        {
            "id": item.id,
            "name": item.name,
            "quantity": item.quantity,
            "minimum_quantity": item.minimum_quantity,
        }
        for item in items
        if item.minimum_quantity is not None
        and item.minimum_quantity > 0
        and item.quantity <= item.minimum_quantity
    ]

    out_movements_qs = StockMovement.objects.filter(
        tenant=tenant, movement_type=StockMovement.MovementType.OUT
    )
    if start_dt is not None:
        out_movements_qs = out_movements_qs.filter(created_at__gte=start_dt)
    if end_dt is not None:
        out_movements_qs = out_movements_qs.filter(created_at__lte=end_dt)

    out_by_item = {
        row["item_id"]: row["total_out"] or 0
        for row in out_movements_qs.values("item_id").annotate(
            total_out=Sum("quantity")
        )
    }

    turnover = []
    for item in items:
        quantity_out = out_by_item.get(item.id, 0)
        turnover_rate = (
            round(quantity_out / item.quantity, 2) if item.quantity > 0 else None
        )
        turnover.append(
            {
                "item_id": item.id,
                "item_name": item.name,
                "quantity_out": quantity_out,
                "current_quantity": item.quantity,
                "turnover_rate": turnover_rate,
            }
        )

    return {
        "stock_active": True,
        "total_stock_value": total_stock_value,
        "low_stock_items_count": len(low_stock_items),
        "low_stock_items": low_stock_items,
        "turnover": turnover,
    }


def get_cogs_and_margin(tenant, start_dt, end_dt, revenue_total) -> dict:
    """COGS e margem do período, para a seção opcional do relatório de faturamento.

    Retorna `stock_active=False` e `product_cost_total`/`margin_total` como
    `None` (sem erro) quando o tenant não usa estoque.
    """
    if not tenant_has_active_stock(tenant):
        return {
            "stock_active": False,
            "product_cost_total": None,
            "margin_total": None,
        }

    out_movements_qs = StockMovement.objects.filter(
        tenant=tenant,
        movement_type=StockMovement.MovementType.OUT,
        created_at__gte=start_dt,
        created_at__lte=end_dt,
    ).annotate(item_unit_cost=F("item__unit_cost"))

    product_cost_total = Decimal("0.00")
    for row in out_movements_qs.values("quantity", "item_unit_cost"):
        unit_cost = row["item_unit_cost"] or Decimal("0")
        product_cost_total += unit_cost * row["quantity"]

    margin_total = Decimal(str(revenue_total or 0)) - product_cost_total

    return {
        "stock_active": True,
        "product_cost_total": product_cost_total,
        "margin_total": margin_total,
    }
