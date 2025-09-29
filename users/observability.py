from prometheus_client import Counter, REGISTRY


def _get_or_create_counter(name: str, documentation: str, labelnames: tuple[str, ...]) -> Counter:
    existing = REGISTRY._names_to_collectors.get(name)  # type: ignore[attr-defined]
    if existing is not None:
        return existing  # type: ignore[return-value]
    return Counter(name, documentation, labelnames)


USERS_AUTH_EVENTS_TOTAL = _get_or_create_counter(
    "users_auth_events_total",
    "Total de eventos de autenticação self-service (users)",
    ("event", "result"),
)

USERS_THROTTLED_TOTAL = _get_or_create_counter(
    "users_throttled_total",
    "Total de requisições self-service bloqueadas por throttling",
    ("scope",),
)

