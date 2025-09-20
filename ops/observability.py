"""Observabilidade para endpoints do console Ops."""

from prometheus_client import Counter, REGISTRY


def _get_or_create_counter(name: str, documentation: str, labelnames: tuple[str, ...]) -> Counter:
    existing = REGISTRY._names_to_collectors.get(name)  # type: ignore[attr-defined]
    if existing is not None:
        return existing  # type: ignore[return-value]
    return Counter(name, documentation, labelnames)


OPS_AUTH_EVENTS_TOTAL = _get_or_create_counter(
    "ops_auth_events_total",
    "Total de eventos de autenticação do console Ops",
    ("event", "result", "role"),
)

OPS_NOTIFICATIONS_RESEND_TOTAL = _get_or_create_counter(
    "ops_notifications_resend_total",
    "Total de reenvios de notificações iniciados pelo console Ops",
    ("channel", "result"),
)

OPS_LOCKOUTS_CLEARED_TOTAL = _get_or_create_counter(
    "ops_lockouts_cleared_total",
    "Total de lockouts limpos pelo console Ops",
    ("result",),
)
