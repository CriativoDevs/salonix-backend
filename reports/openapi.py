# reports/openapi.py

from drf_spectacular.types import OpenApiTypes

RESP_OVERVIEW_JSON = {
    "type": "object",
    "properties": {
        "appointments_total": {"type": "integer", "example": 120},
        "appointments_completed": {"type": "integer", "example": 95},
        "revenue_total": {"type": "number", "example": 155.0},
        "avg_ticket": {"type": "number", "example": 51.67},
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
