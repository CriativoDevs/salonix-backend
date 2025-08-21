from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework import status
from reports.throttling import PerUserScopedRateThrottle

from django.conf import settings
from django.db import models
from django.db.models import Sum, Count, F
from django.db.models.functions import TruncDay
from django.http import HttpResponse
from django.utils import timezone

from drf_spectacular.utils import (
    extend_schema,
    OpenApiParameter,
)
from drf_spectacular.types import OpenApiTypes

from urllib.parse import urlencode

from core.models import Appointment
from users.models import UserFeatureFlags
from reports.observability import observe_request, REPORTS_THROTTLED
from reports.openapi import (
    RESP_OVERVIEW_JSON,
    RESP_TOP_SERVICES_JSON,
    RESP_REVENUE_JSON,
    RESP_CSV_OVERVIEW,
    RESP_CSV_TOP_SERVICES,
    RESP_CSV_REVENUE,
)
from reports.utils.cache import cache_drf_response
from reports.utils.guards import require_reports_enabled

from datetime import timedelta

import csv
import io
import logging


COMPLETED_STATUSES = ("completed", "paid")
logger = logging.getLogger("reports")


# === Helpers para adaptar aos nomes reais do teu modelo ===
def _pick_datetime_field(model):
    """
    Escolhe um campo datetime do Appointment. No teu schema, existe 'created_at'.
    Se no futuro houver outro (ex.: 'start_at'), a prioridade abaixo cuida disso.
    """
    preferred = {
        "created_at",
        "date",
        "start",
        "start_at",
        "start_time",
        "scheduled_for",
        "datetime",
    }
    dt_fields = [f for f in model._meta.fields if isinstance(f, models.DateTimeField)]
    by_name = [f for f in dt_fields if f.name in preferred]
    return by_name[0].name if by_name else (dt_fields[0].name if dt_fields else None)


def _pick_price_source():
    """
    Preferimos somar um DecimalField do Appointment (se existir).
    Como no teu modelo atual não há price no Appointment, usamos o preço do Service.
    """
    # Verifica se Appointment tem algum DecimalField "de preço"
    preferred_price = {"price", "price_eur", "amount", "amount_eur", "total_price"}
    dec_fields = [
        f for f in Appointment._meta.fields if isinstance(f, models.DecimalField)
    ]
    for f in dec_fields:
        if f.name in preferred_price:
            return f.name, None  # (field_name_on_appointment, None)
    # Fallback: preço do serviço
    # Ajuste o nome abaixo se o preço do Service tiver outro nome
    return None, "service__price_eur"  # (None, annotation via F())


DATE_FIELD = _pick_datetime_field(Appointment)
APPT_PRICE_FIELD, SERVICE_PRICE_LOOKUP = _pick_price_source()


def _price_sum():
    return Sum(APPT_PRICE_FIELD) if APPT_PRICE_FIELD else Sum(F(SERVICE_PRICE_LOOKUP))


def _parse_iso_dt(s: str):
    """Aceita 'YYYY-MM-DD' ou datetime ISO; retorna datetime aware em timezone atual."""
    if not s:
        return None
    dt = timezone.datetime.fromisoformat(s)
    if dt.tzinfo is None:
        # interpretar como horário local do server e tornar aware
        return timezone.make_aware(dt)
    return dt


def _date_range(request):
    to_str = request.query_params.get("to")
    from_str = request.query_params.get("from")
    now = timezone.now()
    end = _parse_iso_dt(to_str) or now
    start = _parse_iso_dt(from_str) or (end - timedelta(days=30))
    return start, end


def _get_limit_offset(request):
    cfg = getattr(settings, "REPORTS_PAGINATION", {})
    default_limit = int(cfg.get("DEFAULT_LIMIT", 50))
    max_limit = int(cfg.get("MAX_LIMIT", 500))

    try:
        limit = int(request.query_params.get("limit", default_limit))
    except (TypeError, ValueError):
        limit = default_limit

    try:
        offset = int(request.query_params.get("offset", 0))
    except (TypeError, ValueError):
        offset = 0

    # sane bounds
    limit = max(0, min(limit, max_limit))
    offset = max(0, offset)
    return limit, offset


def _set_pagination_headers(response, *, total, limit, offset, request):
    response["X-Total-Count"] = str(total)
    response["X-Limit"] = str(limit)
    response["X-Offset"] = str(offset)

    # Link header (RFC 5988) com prev/next
    links = []

    def _url(new_offset):
        q = request.query_params.copy()
        q["offset"] = new_offset
        q["limit"] = limit
        return request.build_absolute_uri(f"{request.path}?{urlencode(q)}")

    if offset > 0:
        links.append(f'<{_url(max(0, offset - limit))}>; rel="prev"')
    if offset + limit < total:
        links.append(f'<{_url(offset + limit)}>; rel="next"')

    if links:
        response["Link"] = ", ".join(links)
    return response


PARAM_FROM = OpenApiParameter(
    name="from",
    type=OpenApiTypes.DATETIME,
    location=OpenApiParameter.QUERY,
    description="Data/hora inicial (ISO-8601, UTC). Se ausente, usa `now-30d`.",
    required=False,
)
PARAM_TO = OpenApiParameter(
    name="to",
    type=OpenApiTypes.DATETIME,
    location=OpenApiParameter.QUERY,
    description="Data/hora final (ISO-8601, UTC). Se ausente, usa `now`.",
    required=False,
)
PARAM_LIMIT = OpenApiParameter(
    name="limit",
    type=OpenApiTypes.INT,
    location=OpenApiParameter.QUERY,
    description="Limite de itens (padrão e máx. definidos em settings.REPORTS_PAGINATION).",
    required=False,
)
PARAM_OFFSET = OpenApiParameter(
    name="offset",
    type=OpenApiTypes.INT,
    location=OpenApiParameter.QUERY,
    description="Deslocamento para paginação.",
    required=False,
)
PARAM_INTERVAL = OpenApiParameter(
    name="interval",
    type=OpenApiTypes.STR,
    location=OpenApiParameter.QUERY,
    description="Agrupamento por período.",
    required=False,
    enum=["day", "week", "month"],
)


@extend_schema(
    tags=["Reports"],
    summary="Resumo (mock inicial)",
    responses={
        200: {
            "type": "object",
            "properties": {
                "range": {"type": "string", "example": "last_30_days"},
                "generated_at": {"type": "string", "format": "date-time"},
                "appointments_total": {"type": "integer", "example": 42},
                "revenue_estimated": {
                    "type": "number",
                    "format": "float",
                    "example": 1234.56,
                },
            },
        },
        403: OpenApiTypes.OBJECT,
    },
)
class ReportsSummaryView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        flags, _ = UserFeatureFlags.objects.get_or_create(user=request.user)
        if not flags.reports_enabled:
            return Response(
                {"detail": "Módulo de relatórios desativado."},
                status=status.HTTP_403_FORBIDDEN,
            )
        # Mock inicial
        data = {
            "range": "last_30_days",
            "generated_at": timezone.now(),
            "appointments_total": 42,
            "revenue_estimated": 1234.56,
        }
        return Response(data, status=status.HTTP_200_OK)


class _BaseReports(APIView):
    permission_classes = [IsAuthenticated]
    throttle_classes = (PerUserScopedRateThrottle,)
    throttle_scope = "reports"

    def _guard(self, request):
        ff, _ = UserFeatureFlags.objects.get_or_create(user=request.user)
        if not (ff.is_pro and ff.reports_enabled):
            return Response({"detail": "Módulo de relatórios desativado."}, status=403)

    # garanta que 403 prevaleça sobre throttle
    def get_throttles(self):
        request = getattr(self, "request", None)
        if request is not None:
            ff, _ = UserFeatureFlags.objects.get_or_create(user=request.user)
            if not (ff.is_pro and ff.reports_enabled):
                # sem throttling para quem nem tem acesso
                return []
        return [throttle() for throttle in self.throttle_classes]

    def throttled(self, request, wait):
        endpoint = request.path
        REPORTS_THROTTLED.labels(endpoint=endpoint).inc()
        logger.warning(
            "reports_throttled",
            extra={
                "request_id": getattr(request, "request_id", "-"),
                "endpoint": endpoint,
                "user_id": getattr(request.user, "id", None),
                "is_pro": getattr(
                    getattr(
                        UserFeatureFlags.objects.filter(user=request.user).first(),
                        "is_pro",
                        None,
                    ),
                    "__bool__",
                    lambda: None,
                )(),
            },
        )
        super().throttled(request, wait)


class OverviewReportView(_BaseReports):
    throttle_classes = (PerUserScopedRateThrottle,)
    throttle_scope = "reports"

    @require_reports_enabled
    @cache_drf_response(
        prefix="reports:overview:json",
        ttl=settings.REPORTS_CACHE_TTL["overview_json"],
        vary_on_params=[],  # sem from/to no JSON atual
        vary_on_user=True,
        view_label="overview",
        format_label="json",
    )
    @extend_schema(
        tags=["Reports"],
        summary="Overview (contagens e receita)",
        parameters=[PARAM_FROM, PARAM_TO],
        responses={200: RESP_OVERVIEW_JSON, 403: OpenApiTypes.OBJECT},
    )
    @observe_request(endpoint="/api/reports/overview/")
    def get(self, request):

        start, end = _date_range(request)
        date_gte = {f"{DATE_FIELD}__gte": start}
        date_lte = {f"{DATE_FIELD}__lte": end}

        qs = Appointment.objects.filter(**date_gte, **date_lte)
        total = qs.count()
        done = qs.filter(status__in=COMPLETED_STATUSES)
        done_count = done.count()

        if APPT_PRICE_FIELD:
            revenue = done.aggregate(total=Sum(APPT_PRICE_FIELD))["total"] or 0
        else:
            revenue = done.aggregate(total=Sum(F(SERVICE_PRICE_LOOKUP)))["total"] or 0

        avg_ticket = (revenue / done_count) if done_count else 0
        return Response(
            {
                "appointments_total": total,
                "appointments_completed": done_count,
                "revenue_total": revenue,
                "avg_ticket": avg_ticket,
            }
        )


class TopServicesReportView(_BaseReports):
    throttle_classes = (PerUserScopedRateThrottle,)
    throttle_scope = "reports"

    @require_reports_enabled
    @cache_drf_response(
        prefix="reports:top_services:json",
        ttl=settings.REPORTS_CACHE_TTL["top_services_json"],
        vary_on_params=["limit", "offset", "from", "to"],  # inclui paginação
        vary_on_user=True,
        view_label="top_services",
        format_label="json",
    )
    @extend_schema(
        tags=["Reports"],
        summary="Top Services",
        parameters=[PARAM_FROM, PARAM_TO, PARAM_LIMIT, PARAM_OFFSET],
        responses={200: RESP_TOP_SERVICES_JSON, 403: OpenApiTypes.OBJECT},
    )
    @observe_request(endpoint="/api/reports/top-services/")
    def get(self, request):

        start, end = _date_range(request)
        date_gte = {f"{DATE_FIELD}__gte": start}
        date_lte = {f"{DATE_FIELD}__lte": end}
        limit, offset = _get_limit_offset(request)

        base = Appointment.objects.filter(
            **date_gte, **date_lte, status__in=COMPLETED_STATUSES
        ).values("service_id", "service__name")

        # agregados
        if APPT_PRICE_FIELD:
            base = base.annotate(qty=Count("id"), revenue=Sum(APPT_PRICE_FIELD))
        else:
            base = base.annotate(qty=Count("id"), revenue=Sum(F(SERVICE_PRICE_LOOKUP)))

        # total de linhas agregadas (serviços distintos no período)
        total = base.count()

        # ordenação + janela
        qs = base.order_by("-qty")[offset : offset + limit]

        data = [
            {
                "service_id": r["service_id"],
                "service_name": r["service__name"],
                "qty": r["qty"],
                "revenue": r["revenue"] or 0,
            }
            for r in qs
        ]

        resp = Response(data)
        return _set_pagination_headers(
            resp, total=total, limit=limit, offset=offset, request=request
        )


class RevenueReportView(_BaseReports):
    throttle_classes = (PerUserScopedRateThrottle,)
    throttle_scope = "reports"

    @require_reports_enabled
    @cache_drf_response(
        prefix="reports:revenue:json",
        ttl=settings.REPORTS_CACHE_TTL["revenue_json"],
        vary_on_params=[
            "interval",
            "from",
            "to",
            "limit",
            "offset",
        ],  # inclui paginação
        vary_on_user=True,
        view_label="revenue",
        format_label="json",
    )
    @extend_schema(
        tags=["Reports"],
        summary="Série de receita por período",
        parameters=[PARAM_FROM, PARAM_TO, PARAM_INTERVAL, PARAM_LIMIT, PARAM_OFFSET],
        responses={200: RESP_REVENUE_JSON, 403: OpenApiTypes.OBJECT},
    )
    @observe_request(endpoint="/api/reports/revenue/")
    def get(self, request):

        start, end = _date_range(request)
        interval = request.query_params.get("interval", "day")
        from django.db.models.functions import TruncDay, TruncWeek, TruncMonth

        trunc = {"day": TruncDay, "week": TruncWeek, "month": TruncMonth}.get(
            interval, TruncDay
        )
        date_gte = {f"{DATE_FIELD}__gte": start}
        date_lte = {f"{DATE_FIELD}__lte": end}
        limit, offset = _get_limit_offset(request)

        base = (
            Appointment.objects.filter(
                **date_gte, **date_lte, status__in=COMPLETED_STATUSES
            )
            .annotate(bucket=trunc(DATE_FIELD))
            .values("bucket")
        )

        if APPT_PRICE_FIELD:
            base = base.annotate(revenue=Sum(APPT_PRICE_FIELD))
        else:
            base = base.annotate(revenue=Sum(F(SERVICE_PRICE_LOOKUP)))

        total = base.count()

        # mantemos ordem crescente por período; paginamos sobre ela
        qs = base.order_by("bucket")[offset : offset + limit]

        data = [{"period_start": r["bucket"], "revenue": r["revenue"] or 0} for r in qs]
        resp = Response({"interval": interval, "series": data})
        return _set_pagination_headers(
            resp, total=total, limit=limit, offset=offset, request=request
        )


class ExportOverviewCSVView(_BaseReports):
    """
    GET /api/reports/overview/export/?from=YYYY-MM-DD&to=YYYY-MM-DD
    Gera um CSV com:
      - bloco de resumo (total agendamentos, completados, receita, ticket médio)
      - série diária de receita (period_start, revenue)
    """

    throttle_classes = (PerUserScopedRateThrottle,)
    throttle_scope = "export_csv"

    @require_reports_enabled
    @cache_drf_response(
        prefix="reports:overview:csv",
        ttl=settings.REPORTS_CACHE_TTL["overview_csv"],
        vary_on_params=["from", "to"],
        vary_on_user=True,
        view_label="overview",
        format_label="csv",
    )
    @extend_schema(
        tags=["Reports"],
        summary="Exportar overview (CSV)",
        parameters=[PARAM_FROM, PARAM_TO],
        responses={200: RESP_CSV_OVERVIEW, 403: OpenApiTypes.OBJECT},
    )
    @observe_request(endpoint="/api/reports/overview/export/")
    def get(self, request):

        start, end = _date_range(request)
        date_gte = {f"{DATE_FIELD}__gte": start}
        date_lte = {f"{DATE_FIELD}__lte": end}

        # Query base
        base_qs = Appointment.objects.filter(**date_gte, **date_lte)
        total_count = base_qs.count()

        done_qs = base_qs.filter(status__in=COMPLETED_STATUSES)
        done_count = done_qs.count()
        revenue_total = done_qs.aggregate(total=_price_sum())["total"] or 0
        avg_ticket = (revenue_total / done_count) if done_count else 0

        # Série diária
        series_qs = (
            done_qs.annotate(bucket=TruncDay(DATE_FIELD))
            .values("bucket")
            .annotate(revenue=_price_sum())
            .order_by("bucket")
        )

        # Monta CSV (duas seções com uma linha em branco)
        buffer = io.StringIO()
        writer = csv.writer(buffer)

        # Cabeçalho e resumo
        writer.writerow(["Overview report"])
        writer.writerow(["Period start", start.isoformat()])
        writer.writerow(["Period end", end.isoformat()])
        writer.writerow([])
        writer.writerow(
            [
                "appointments_total",
                "appointments_completed",
                "revenue_total",
                "avg_ticket",
            ]
        )
        writer.writerow([total_count, done_count, revenue_total, avg_ticket])

        # Linha em branco separadora
        writer.writerow([])
        writer.writerow(["period_start", "revenue"])

        # 👉 iterator() evita carregar toda a queryset em memória
        for row in series_qs.iterator(chunk_size=1000):
            writer.writerow([row["bucket"].date().isoformat(), row["revenue"] or 0])

        csv_content = buffer.getvalue()
        buffer.close()

        filename = f"overview_{start.date().isoformat()}_{end.date().isoformat()}.csv"
        resp = HttpResponse(csv_content, content_type="text/csv; charset=utf-8")
        resp["Content-Disposition"] = f'attachment; filename="{filename}"'
        return resp


class ExportTopServicesCSVView(_BaseReports):
    """
    GET /api/reports/top-services/export/?from=YYYY-MM-DD&to=YYYY-MM-DD

    Gera CSV com as colunas:
      - service_id
      - service_name
      - qty (quantidade de atendimentos completados no período)
      - revenue (soma de receita estimada no período)
    """

    throttle_classes = (PerUserScopedRateThrottle,)
    throttle_scope = "export_csv"

    @require_reports_enabled
    @cache_drf_response(
        prefix="reports:top_services:csv",
        ttl=settings.REPORTS_CACHE_TTL["top_services_csv"],
        vary_on_params=["from", "to"],
        vary_on_user=True,
        view_label="top_services",
        format_label="csv",
    )
    @extend_schema(
        tags=["Reports"],
        summary="Exportar Top Services (CSV)",
        parameters=[PARAM_FROM, PARAM_TO],
        responses={200: RESP_CSV_TOP_SERVICES, 403: OpenApiTypes.OBJECT},
    )
    def get(self, request):

        start, end = _date_range(request)
        date_gte = {f"{DATE_FIELD}__gte": start}
        date_lte = {f"{DATE_FIELD}__lte": end}

        base = Appointment.objects.filter(
            **date_gte, **date_lte, status__in=COMPLETED_STATUSES
        ).values("service_id", "service__name")

        if APPT_PRICE_FIELD:
            base = base.annotate(qty=Count("id"), revenue=Sum(APPT_PRICE_FIELD))
        else:
            base = base.annotate(qty=Count("id"), revenue=Sum(F(SERVICE_PRICE_LOOKUP)))

        qs = base.order_by("-qty", "-revenue", "service__name")

        buffer = io.StringIO()
        w = csv.writer(buffer)

        # cabeçalho + metadados do período
        w.writerow(["Top Services report"])
        w.writerow(["Period start", start.isoformat()])
        w.writerow(["Period end", end.isoformat()])
        w.writerow([])
        w.writerow(["service_id", "service_name", "qty", "revenue"])

        for row in qs.iterator(chunk_size=1000):
            w.writerow(
                [
                    row["service_id"],
                    row["service__name"],
                    row["qty"] or 0,
                    row["revenue"] or 0,
                ]
            )

        csv_content = buffer.getvalue()
        buffer.close()

        filename = (
            f"top_services_{start.date().isoformat()}_{end.date().isoformat()}.csv"
        )
        resp = HttpResponse(csv_content, content_type="text/csv; charset=utf-8")
        resp["Content-Disposition"] = f'attachment; filename="{filename}"'
        return resp


class ExportRevenueCSVView(_BaseReports):
    """
    GET /api/reports/revenue/export/?from=YYYY-MM-DD&to=YYYY-MM-DD&interval=day|week|month

    Gera CSV com as colunas:
      - period_start (início do bucket)
      - revenue (soma no bucket)
    """

    throttle_classes = (PerUserScopedRateThrottle,)
    throttle_scope = "export_csv"

    @require_reports_enabled
    @cache_drf_response(
        prefix="reports:revenue:csv",
        ttl=settings.REPORTS_CACHE_TTL["revenue_csv"],
        vary_on_params=["interval", "from", "to"],
        vary_on_user=True,
        view_label="revenue",
        format_label="csv",
    )
    @extend_schema(
        tags=["Reports"],
        summary="Exportar Revenue Series (CSV)",
        parameters=[PARAM_FROM, PARAM_TO, PARAM_INTERVAL],
        responses={200: RESP_CSV_REVENUE, 403: OpenApiTypes.OBJECT},
    )
    def get(self, request):

        start, end = _date_range(request)
        interval = request.query_params.get("interval", "day")
        from django.db.models.functions import TruncDay, TruncWeek, TruncMonth

        trunc = {"day": TruncDay, "week": TruncWeek, "month": TruncMonth}.get(
            interval, TruncDay
        )

        date_gte = {f"{DATE_FIELD}__gte": start}
        date_lte = {f"{DATE_FIELD}__lte": end}

        base = (
            Appointment.objects.filter(
                **date_gte, **date_lte, status__in=COMPLETED_STATUSES
            )
            .annotate(bucket=trunc(DATE_FIELD))
            .values("bucket")
        )

        if APPT_PRICE_FIELD:
            base = base.annotate(revenue=Sum(APPT_PRICE_FIELD))
        else:
            base = base.annotate(revenue=Sum(F(SERVICE_PRICE_LOOKUP)))

        qs = base.order_by("bucket")

        buffer = io.StringIO()
        w = csv.writer(buffer)

        # cabeçalho + metadados
        w.writerow(["Revenue series report"])
        w.writerow(["Interval", interval])
        w.writerow(["Period start", start.isoformat()])
        w.writerow(["Period end", end.isoformat()])
        w.writerow([])
        w.writerow(["period_start", "revenue"])

        for row in qs.iterator(chunk_size=1000):
            # bucket pode ser None se não houver dados, mas como filtramos por período, é seguro
            dt = row["bucket"]
            w.writerow(
                [
                    (dt.isoformat() if hasattr(dt, "isoformat") else str(dt)),
                    row["revenue"] or 0,
                ]
            )

        csv_content = buffer.getvalue()
        buffer.close()

        filename = f"revenue_{interval}_{start.date().isoformat()}_{end.date().isoformat()}.csv"
        resp = HttpResponse(csv_content, content_type="text/csv; charset=utf-8")
        resp["Content-Disposition"] = f'attachment; filename="{filename}"'
        return resp
