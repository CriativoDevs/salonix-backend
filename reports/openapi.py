# reports/openapi.py

from drf_spectacular.types import OpenApiTypes

RESP_OVERVIEW_JSON = {
    "type": "object",
    "properties": {
        "appointments_total": {"type": "integer", "example": 120},
        "appointments_completed": {"type": "integer", "example": 95},
        "revenue_total": {"type": "number", "example": 155.0},
        "avg_ticket": {"type": "number", "example": 51.67},
        "stock_active": {
            "type": "boolean",
            "description": (
                "BE-REPORTS-01 (#569): true quando o tenant já usa o módulo "
                "de estoque (tem pelo menos um InventoryItem). Quando false, "
                "product_cost_total/margin_total vêm nulos."
            ),
            "example": True,
        },
        "product_cost_total": {
            "type": "number",
            "nullable": True,
            "description": (
                "COGS (Cost of Goods Sold / custo das mercadorias vendidas) do "
                "período: soma de quantidade_saída x unit_cost de todo "
                "StockMovement do tipo 'out' do tenant no período. Não é "
                "ligado a Appointment/Service (não existe esse vínculo no "
                "modelo) — é o consumo de estoque do tenant como um todo, "
                "não o custo de uma venda/serviço específico. Nulo quando "
                "stock_active=false."
            ),
            "example": 32.5,
        },
        "margin_total": {
            "type": "number",
            "nullable": True,
            "description": "revenue_total - product_cost_total (COGS). Nulo quando stock_active=false.",
            "example": 122.5,
        },
    },
}

RESP_INVENTORY_REPORT_JSON = {
    "type": "object",
    "properties": {
        "stock_active": {
            "type": "boolean",
            "description": (
                "BE-REPORTS-01 (#569): true quando o tenant já usa o módulo "
                "de estoque (tem pelo menos um InventoryItem). Quando false, "
                "as demais seções vêm vazias/zeradas (nunca erro)."
            ),
            "example": True,
        },
        "total_stock_value": {
            "type": "number",
            "description": (
                "Valoração do estoque ao custo: soma de quantity x unit_cost "
                "de cada InventoryItem do tenant. Reflete o estado atual, não "
                "depende do período (from/to)."
            ),
            "example": 480.0,
        },
        "low_stock_items_count": {
            "type": "integer",
            "description": "Quantidade de itens com quantity <= minimum_quantity.",
            "example": 2,
        },
        "low_stock_items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "integer"},
                    "name": {"type": "string"},
                    "quantity": {"type": "integer"},
                    "minimum_quantity": {"type": "integer"},
                },
            },
        },
        "turnover": {
            "type": "array",
            "description": (
                "Giro de estoque por item no período: turnover_rate = "
                "quantidade_saída / quantidade_atual. None quando a "
                "quantidade atual do item é zero (divisão indefinida)."
            ),
            "items": {
                "type": "object",
                "properties": {
                    "item_id": {"type": "integer"},
                    "item_name": {"type": "string"},
                    "quantity_out": {"type": "integer"},
                    "current_quantity": {"type": "integer"},
                    "turnover_rate": {"type": "number", "nullable": True},
                },
            },
        },
        "period": {
            "type": "object",
            "description": "Janela from/to usada para calcular quantity_out e turnover_rate.",
            "properties": {
                "start": {"type": "string", "format": "date-time", "nullable": True},
                "end": {"type": "string", "format": "date-time", "nullable": True},
            },
        },
    },
}

RESP_TOP_SERVICES_JSON = {
    "type": "array",
    "items": {
        "type": "object",
        "properties": {
            "service_id": {"type": "integer", "example": 10},
            "service_name": {"type": "string", "example": "Corte de Cabelo"},
            "qty": {"type": "integer", "example": 2},
            "revenue": {"type": "number", "example": 75.00},
        },
    },
    "description": "Cabeçalhos de paginação: X-Total-Count, X-Limit, X-Offset, Link",
}

RESP_REVENUE_JSON = {
    "type": "object",
    "properties": {
        "interval": {"type": "string", "enum": ["day", "week", "month"]},
        "series": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "period_start": {"type": "string", "format": "date-time"},
                    "revenue": {"type": "number"},
                    "appointment_count": {"type": "integer"},
                },
            },
        },
    },
    "description": "Cabeçalhos de paginação: X-Total-Count, X-Limit, X-Offset, Link",
}

# Para CSVs, basta indicar binário:
RESP_CSV_OVERVIEW = OpenApiTypes.BINARY
RESP_CSV_TOP_SERVICES = OpenApiTypes.BINARY
RESP_CSV_REVENUE = OpenApiTypes.BINARY
