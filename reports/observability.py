import time
import logging
from prometheus_client import Counter, Histogram
from django.conf import settings

logger = logging.getLogger("reports")

ENABLED = getattr(settings, "OBSERVABILITY_ENABLED", True)

REPORTS_REQUESTS = Counter(
    "reports_requests_total",
    "Total de requests em /api/reports/*",
    labelnames=("endpoint", "result"),
)

REPORTS_LATENCY = Histogram(
    "reports_request_duration_seconds",
    "Duração das requests em /api/reports/*",
    labelnames=("endpoint",),
    buckets=(0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10),
)

REPORTS_THROTTLED = Counter(
    "reports_throttled_total",
    "Total de respostas 429 em /api/reports/*",
    labelnames=("endpoint",),
)

REPORTS_CSV_BYTES = Counter(
    "reports_csv_bytes_total",
    "Bytes de CSV gerados",
    labelnames=("endpoint",),
)

REPORTS_CSV_ROWS = Counter(
    "reports_csv_rows_total",
    "Linhas em CSVs geradas",
    labelnames=("endpoint",),
)


def _extra(request, endpoint, user, is_pro=None, event="event"):
    return {
        "request_id": getattr(request, "request_id", "-"),
        "endpoint": endpoint,
        "user_id": getattr(user, "id", None),
        "is_pro": is_pro,
        "event": event,
    }


def observe_request(endpoint):
    """Decorator: mede tempo + conta sucesso/erro e loga com extras."""

    def _wrap(func):
        def _inner(self, request, *args, **kwargs):
            if not ENABLED:
                return func(self, request, *args, **kwargs)
            start = time.time()
            try:
                resp = func(self, request, *args, **kwargs)
                dur = time.time() - start
                REPORTS_LATENCY.labels(endpoint=endpoint).observe(dur)
                REPORTS_REQUESTS.labels(
                    endpoint=endpoint, result=str(resp.status_code)
                ).inc()

                # log estruturado de sucesso
                ff = None
                try:
                    from users.models import UserFeatureFlags

                    ff, _ = UserFeatureFlags.objects.get_or_create(user=request.user)
                except Exception:
                    pass
                logger.info(
                    "reports_request_ok",
                    extra=_extra(
                        request,
                        endpoint,
                        request.user,
                        getattr(ff, "is_pro", None),
                        "ok",
                    ),
                )
                return resp
            except Exception as exc:
                dur = time.time() - start
                REPORTS_LATENCY.labels(endpoint=endpoint).observe(dur)
                REPORTS_REQUESTS.labels(endpoint=endpoint, result="500").inc()
                logger.exception(
                    "reports_request_error",
                    extra=_extra(request, endpoint, request.user, event="error"),
                )
                raise

        return _inner

    return _wrap


def track_csv(endpoint, bytes_len: int, rows: int):
    if not ENABLED:
        return
    REPORTS_CSV_BYTES.labels(endpoint=endpoint).inc(bytes_len)
    REPORTS_CSV_ROWS.labels(endpoint=endpoint).inc(rows)
