from prometheus_client import Counter, REGISTRY


def _get_or_create_counter(
    name: str, documentation: str, labelnames: tuple[str, ...]
) -> Counter:
    existing = REGISTRY._names_to_collectors.get(name)  # type: ignore[attr-defined]
    if existing is not None:
        return existing  # type: ignore[return-value]
    return Counter(name, documentation, labelnames)


PAYMENTS_SETTINGS_UPDATED_TOTAL = _get_or_create_counter(
    "payments_settings_updated_total",
    "Total de atualizações de configurações de pagamentos (Stripe settings)",
    ("result",),
)

COMM_AUTO_RENEWAL_FAILURES_TOTAL = _get_or_create_counter(
    "comm_auto_renewal_failures_total",
    "Total de falhas na renovação automática de crédito de comunicação, por motivo",
    ("reason",),
)
