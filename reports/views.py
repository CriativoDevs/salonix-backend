from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated, BasePermission
from rest_framework.response import Response
from rest_framework import status
from reports.throttling import PerUserScopedRateThrottle
from users.feature_flags import RequiresFeatureFlag

from django.conf import settings
from django.db import models
from django.db.models import Sum, Count, F, Case, When, Value, BooleanField, Q
from django.db.models.functions import TruncDay
from django.http import HttpResponse
from typing import Any, Optional
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

# from reports.utils.guards import require_reports_enabled  # Removido - usando permissions agora

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
    from typing import cast

    return (
        Sum(APPT_PRICE_FIELD)
        if APPT_PRICE_FIELD
        else Sum(F(cast(str, SERVICE_PRICE_LOOKUP)))
    )


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

    # Se from não foi fornecido, usa período padrão de 30 dias
    # Considera diferentes tamanhos de mês (28, 29, 30, 31 dias)
    if from_str is None:
        # Subtrai 30 dias da data final, respeitando calendário
        start = end - timedelta(days=30)
    else:
        start = _parse_iso_dt(from_str)

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
    description="Data/hora inicial (ISO-8601, UTC). Se ausente, usa período padrão de 30 dias antes da data final.",
    required=False,
)
PARAM_TO = OpenApiParameter(
    name="to",
    type=OpenApiTypes.DATETIME,
    location=OpenApiParameter.QUERY,
    description="Data/hora final (ISO-8601, UTC). Se ausente, usa data/hora atual.",
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

    def get(self, request) -> HttpResponse:
        flags, _ = UserFeatureFlags.objects.get_or_create(user=request.user)
        if not flags.reports_enabled:
            return Response(
                {"detail": "Módulo de relatórios desativado."},
                status=status.HTTP_403_FORBIDDEN,
            )

        # Processar parâmetros de data
        start, end = _date_range(request)
        date_gte = {f"{DATE_FIELD}__gte": start}
        date_lte = {f"{DATE_FIELD}__lte": end}

        # Filtrar appointments por período e por tenant
        appointments_qs = Appointment.objects.filter(
            **date_gte,
            **date_lte,
            status__in=COMPLETED_STATUSES,
            tenant=getattr(request.user, "tenant", None),
        )

        # Calcular total de appointments
        appointments_total = appointments_qs.count()

        # Calcular receita estimada
        if APPT_PRICE_FIELD:
            revenue_estimated = (
                appointments_qs.aggregate(total=Sum(APPT_PRICE_FIELD))["total"] or 0.0
            )
        else:
            revenue_estimated = (
                appointments_qs.aggregate(total=_price_sum())["total"] or 0.0
            )

        # Determinar range baseado nos parâmetros
        from_param = request.query_params.get("from")
        to_param = request.query_params.get("to")

        if not from_param and not to_param:
            range_label = "last_30_days"
        else:
            range_label = f"custom_{start.date()}_{end.date()}"

        data = {
            "range": range_label,
            "generated_at": timezone.now(),
            "appointments_total": appointments_total,
            "revenue_estimated": float(revenue_estimated),
        }
        return Response(data, status=status.HTTP_200_OK)


class _BaseReports(APIView):
    throttle_classes = (PerUserScopedRateThrottle,)
    throttle_scope = "reports"

    def get_permissions(self):
        """Retorna permissions incluindo feature flag de reports"""
        return [
            IsAuthenticated(),
            RequiresBasicReports(),  # Mudança: Base agora exige apenas Basic
        ]

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

    # Overview é Basic, então herda _BaseReports (RequiresBasicReports)

    @cache_drf_response(
        prefix="reports:overview:json",
        ttl=settings.REPORTS_CACHE_TTL["overview_json"],
        vary_on_params=["from", "to"],
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

        qs = Appointment.objects.filter(
            **date_gte,
            **date_lte,
            tenant=getattr(request.user, "tenant", None),
        )
        total = qs.count()
        done = qs.filter(status__in=COMPLETED_STATUSES)
        done_count = done.count()

        if APPT_PRICE_FIELD:
            revenue = done.aggregate(total=Sum(APPT_PRICE_FIELD))["total"] or 0
        else:
            revenue = done.aggregate(total=_price_sum())["total"] or 0

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

    def get_permissions(self):
        """Top Services exige plano Pro"""
        return [
            IsAuthenticated(),
            RequiresProReports(),
        ]

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
            **date_gte,
            **date_lte,
            status__in=COMPLETED_STATUSES,
            tenant=getattr(request.user, "tenant", None),
        ).values("service_id", "service__name")

        # agregados
        if APPT_PRICE_FIELD:
            base = base.annotate(qty=Count("id"), revenue=Sum(APPT_PRICE_FIELD))
        else:
            base = base.annotate(qty=Count("id"), revenue=_price_sum())

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


class RevenueSeriesReportView(_BaseReports):
    throttle_classes = (PerUserScopedRateThrottle,)
    throttle_scope = "reports"

    def get_permissions(self):
        """Revenue Series exige plano Pro"""
        return [
            IsAuthenticated(),
            RequiresProReports(),
        ]

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
                **date_gte,
                **date_lte,
                status__in=COMPLETED_STATUSES,
                tenant=getattr(request.user, "tenant", None),
            )
            .annotate(bucket=trunc(DATE_FIELD))
            .values("bucket")
        )

        if APPT_PRICE_FIELD:
            base = base.annotate(
                revenue=Sum(APPT_PRICE_FIELD), appointment_count=Count("id")
            )
        else:
            base = base.annotate(revenue=_price_sum(), appointment_count=Count("id"))

        total = base.count()

        # mantemos ordem crescente por período; paginamos sobre ela
        qs = base.order_by("bucket")[offset : offset + limit]

        data = [
            {
                "period_start": r["bucket"],
                "revenue": r["revenue"] or 0,
                "appointment_count": r["appointment_count"] or 0,
            }
            for r in qs
        ]
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
        try:
            start, end = _date_range(request)
            date_gte = {f"{DATE_FIELD}__gte": start}
            date_lte = {f"{DATE_FIELD}__lte": end}

            try:
                base_qs = Appointment.objects.filter(
                    **date_gte,
                    **date_lte,
                    tenant=getattr(request.user, "tenant", None),
                )
                total_count = base_qs.count()

                done_qs = base_qs.filter(status__in=COMPLETED_STATUSES)
                done_count = done_qs.count()

                # soma de receita (robusta para ambos os casos: price no Appointment ou via Service)
                revenue_total = done_qs.aggregate(total=_price_sum()).get("total") or 0
                avg_ticket = (revenue_total / done_count) if done_count else 0
            except Exception as e:
                logger.error(f"Error querying data for overview export: {e}")
                return Response(
                    {"error": "Erro ao consultar dados. Tente novamente."},
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR,
                )

            # Série diária
            try:
                series_qs = (
                    done_qs.annotate(bucket=TruncDay(DATE_FIELD))
                    .values("bucket")
                    .annotate(revenue=_price_sum())
                    .order_by("bucket")
                )
            except Exception as e:
                logger.error(f"Error creating daily series query: {e}")
                return Response(
                    {"error": "Erro ao processar série diária."},
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR,
                )

            try:
                buffer = io.StringIO()
                writer = csv.writer(buffer)

                # Importar utilitários de formatação
                from reports.utils.csv_formatter import (
                    write_timely_one_header,
                    format_currency,
                    format_date_pt,
                )

                # Cabeçalho bonito com branding TimelyOne
                write_timely_one_header(writer, "Relatório Geral", start, end)

                # Bloco de resumo com nomes traduzidos
                writer.writerow(["📈 RESUMO EXECUTIVO"])
                writer.writerow([])
                writer.writerow(
                    [
                        "Agendamentos Totais",
                        "Agendamentos Concluídos",
                        "Receita Total",
                        "Ticket Médio",
                    ]
                )
                writer.writerow(
                    [
                        int(total_count or 0),
                        int(done_count or 0),
                        format_currency(float(revenue_total or 0)),
                        format_currency(float(avg_ticket or 0)),
                    ]
                )

                # Série diária com formatação melhorada
                writer.writerow([])
                writer.writerow(["📊 RECEITA DIÁRIA"])
                writer.writerow([])
                writer.writerow(["Data", "Receita"])

                # Itera com segurança; evita KeyError e None
                try:
                    for row in series_qs.iterator(chunk_size=1000):
                        bucket: Optional[Any] = row.get("bucket")
                        revenue = row.get("revenue") or 0
                        # bucket pode ser datetime, date, ou None; normalize
                        if bucket is None:
                            period = ""
                        elif hasattr(bucket, "date"):
                            period = format_date_pt(bucket.date())
                        elif hasattr(bucket, "isoformat"):
                            period = format_date_pt(bucket)
                        else:
                            period = str(bucket)
                        writer.writerow([period, format_currency(float(revenue))])
                except Exception as e:
                    logger.error(f"Error processing daily series data: {e}")
                    writer.writerow(["Erro ao processar dados diários", ""])

                csv_content = buffer.getvalue()
                buffer.close()
            except Exception as e:
                logger.error(f"Error generating CSV content: {e}")
                return Response(
                    {"error": "Erro ao gerar arquivo CSV."},
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR,
                )

            filename = (
                f"overview_{start.date().isoformat()}_{end.date().isoformat()}.csv"
            )
            resp = HttpResponse(
                csv_content.encode("utf-8"), content_type="text/csv; charset=utf-8"
            )
            resp["Content-Disposition"] = f'attachment; filename="{filename}"'
            # cabeçalhos defensivos (opcional)
            resp["X-Content-Type-Options"] = "nosniff"
            resp["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
            resp["Pragma"] = "no-cache"

            logger.info(
                f"Overview CSV export completed successfully. Period: {start.date()} to {end.date()}"
            )
            return resp

        except Exception as e:
            logger.error(f"Unexpected error in overview CSV export: {e}", exc_info=True)
            return Response(
                {"error": "Erro interno do servidor. Tente novamente mais tarde."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


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
    def get(self, request) -> HttpResponse:
        start, end = _date_range(request)
        tenant = getattr(request.user, "tenant", None)
        date_gte = {f"{DATE_FIELD}__gte": start}
        date_lte = {f"{DATE_FIELD}__lte": end}

        base = Appointment.objects.filter(
            **date_gte,
            **date_lte,
            status__in=COMPLETED_STATUSES,
            tenant=tenant,
        ).values("service_id", "service__name")

        if APPT_PRICE_FIELD:
            base = base.annotate(qty=Count("id"), revenue=Sum(APPT_PRICE_FIELD))
        else:
            base = base.annotate(qty=Count("id"), revenue=_price_sum())

        qs = base.order_by("-qty", "-revenue", "service__name")

        buffer = io.StringIO()
        w = csv.writer(buffer)

        # Importar utilitários de formatação
        from reports.utils.csv_formatter import (
            write_timely_one_header,
            format_currency,
            translate_column_names,
        )

        # Cabeçalho bonito com branding TimelyOne
        write_timely_one_header(w, "Relatório Top Serviços", start, end)

        # Cabeçalhos traduzidos
        headers = translate_column_names(
            {
                "service_id": "ID do Serviço",
                "service_name": "Nome do Serviço",
                "qty": "Quantidade",
                "revenue": "Receita",
            }
        )

        w.writerow(["🏆 TOP SERVIÇOS"])
        w.writerow([])
        w.writerow(list(headers.values()))

        for row in qs.iterator(chunk_size=1000):
            w.writerow(
                [
                    row["service_id"],
                    row["service__name"],
                    row["qty"] or 0,
                    format_currency(row["revenue"] or 0),
                ]
            )

        csv_content = buffer.getvalue()
        buffer.close()

        filename = (
            f"top_services_{start.date().isoformat()}_{end.date().isoformat()}.csv"
        )
        resp = HttpResponse(
            csv_content.encode("utf-8"), content_type="text/csv; charset=utf-8"
        )
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
    def get(self, request) -> HttpResponse:
        start, end = _date_range(request)
        tenant = getattr(request.user, "tenant", None)
        interval = request.query_params.get("interval", "day")
        from django.db.models.functions import TruncDay, TruncWeek, TruncMonth

        trunc = {"day": TruncDay, "week": TruncWeek, "month": TruncMonth}.get(
            interval, TruncDay
        )

        date_gte = {f"{DATE_FIELD}__gte": start}
        date_lte = {f"{DATE_FIELD}__lte": end}

        base = (
            Appointment.objects.filter(
                **date_gte,
                **date_lte,
                status__in=COMPLETED_STATUSES,
                tenant=tenant,
            )
            .annotate(bucket=trunc(DATE_FIELD))
            .values("bucket")
        )

        if APPT_PRICE_FIELD:
            base = base.annotate(revenue=Sum(APPT_PRICE_FIELD))
        else:
            base = base.annotate(revenue=_price_sum())

        qs = base.order_by("bucket")

        buffer = io.StringIO()
        w = csv.writer(buffer)

        # Importar utilitários de formatação
        from reports.utils.csv_formatter import (
            write_timely_one_header,
            format_currency,
            format_date_pt,
            translate_column_names,
        )

        # Cabeçalho bonito com branding TimelyOne
        write_timely_one_header(
            w, f"Relatório de Receita ({interval.title()})", start, end
        )

        # Cabeçalhos traduzidos
        headers = translate_column_names(
            {"period_start": "Período", "revenue": "Receita"}
        )

        w.writerow([f"📊 RECEITA POR {interval.upper()}"])
        w.writerow([])
        w.writerow(list(headers.values()))

        for row in qs.iterator(chunk_size=1000):
            # bucket pode ser None se não houver dados, mas como filtramos por período, é seguro
            dt = row["bucket"]
            w.writerow(
                [
                    format_date_pt(dt) if hasattr(dt, "isoformat") else str(dt),
                    format_currency(row["revenue"] or 0),
                ]
            )

        csv_content = buffer.getvalue()
        buffer.close()

        filename = f"revenue_{interval}_{start.date().isoformat()}_{end.date().isoformat()}.csv"
        resp = HttpResponse(
            csv_content.encode("utf-8"), content_type="text/csv; charset=utf-8"
        )
        resp["Content-Disposition"] = f'attachment; filename="{filename}"'
        return resp


# === Novas classes de permissão para relatórios básicos e avançados ===


class RequiresBasicReports(BasePermission):
    """
    Permission que permite acesso a relatórios básicos.
    Todos os planos (Basic, Standard, Pro) têm acesso.
    """

    def has_permission(self, request, view):
        if not hasattr(request, "user") or not request.user.is_authenticated:
            return False

        if not hasattr(request.user, "tenant") or request.user.tenant is None:
            return False

        tenant = request.user.tenant
        return tenant.can_use_basic_reports()


class RequiresProReports(BasePermission):
    """
    Permission para relatórios Pro (top-services, revenue, retention, advanced export).
    Exige plano Pro ou Founder.
    """

    def has_permission(self, request, view):
        if not hasattr(request, "user") or not request.user.is_authenticated:
            return False

        if not hasattr(request.user, "tenant") or request.user.tenant is None:
            return False

        tenant = request.user.tenant
        return tenant.can_use_advanced_reports()


# === Views para relatórios básicos e avançados ===


@extend_schema(
    tags=["Reports"],
    summary="Relatórios Básicos - Disponível para todos os planos",
    responses={
        200: {
            "type": "object",
            "properties": {
                "summary": {"type": "object"},
                "overview": {"type": "object"},
            },
        },
        403: OpenApiTypes.OBJECT,
    },
)
class BasicReportsView(APIView):
    """
    Endpoint para relatórios básicos.
    Disponível para todos os planos que têm acesso a relatórios.
    """

    permission_classes = [IsAuthenticated, RequiresBasicReports]
    throttle_classes = (PerUserScopedRateThrottle,)
    throttle_scope = "reports"

    @observe_request(endpoint="/api/reports/basic/")
    def get(self, request):
        """Retorna relatórios básicos: summary e overview"""

        # Reutiliza a lógica das views existentes
        summary_view = ReportsSummaryView()
        summary_view.request = request
        summary_response = summary_view.get(request)

        overview_view = OverviewReportView()
        overview_view.request = request
        overview_response = overview_view.get(request)

        return Response(
            {
                "summary": (
                    summary_response.data
                    if hasattr(summary_response, "data")
                    else summary_response.content
                ),
                "overview": (
                    overview_response.data
                    if hasattr(overview_response, "data")
                    else overview_response.content
                ),
            }
        )


class ExportBasicReportsCSVView(_BaseReports):
    """
    GET /api/reports/basic/export/?from=YYYY-MM-DD&to=YYYY-MM-DD
    Gera um CSV com relatórios básicos (summary + overview)
    """

    permission_classes = [IsAuthenticated, RequiresBasicReports]
    throttle_classes = (PerUserScopedRateThrottle,)
    throttle_scope = "export_csv"

    @cache_drf_response(
        prefix="reports:basic:csv",
        ttl=settings.REPORTS_CACHE_TTL.get("basic_csv", 300),  # 5 min default
        vary_on_params=["from", "to"],
        vary_on_user=True,
        view_label="basic",
        format_label="csv",
    )
    @extend_schema(
        tags=["Reports"],
        summary="Exportar Relatórios Básicos (CSV)",
        parameters=[PARAM_FROM, PARAM_TO],
        responses={200: RESP_CSV_OVERVIEW, 403: OpenApiTypes.OBJECT},
    )
    @observe_request(endpoint="/api/reports/basic/export/")
    def get(self, request) -> HttpResponse:
        """Exporta relatórios básicos em CSV"""

        try:
            start, end = _date_range(request)
            tenant = getattr(request.user, "tenant", None)
            date_gte = {f"{DATE_FIELD}__gte": start}
            date_lte = {f"{DATE_FIELD}__lte": end}

            # Buscar dados básicos (mesmo que ExportOverviewCSVView)
            qs = Appointment.objects.filter(**date_gte, **date_lte, tenant=tenant)
            total_count = qs.count()
            done_qs = qs.filter(status__in=COMPLETED_STATUSES)
            done_count = done_qs.count()

            if APPT_PRICE_FIELD:
                revenue = done_qs.aggregate(total=Sum(APPT_PRICE_FIELD))["total"] or 0
            else:
                revenue = done_qs.aggregate(total=_price_sum())["total"] or 0

            avg_ticket = (revenue / done_count) if done_count else 0

            # Série diária
            series_qs = (
                done_qs.annotate(bucket=TruncDay(DATE_FIELD))
                .values("bucket")
                .annotate(revenue=_price_sum())
                .order_by("bucket")
            )

            buffer = io.StringIO()
            writer = csv.writer(buffer)

            # Importar utilitários de formatação
            from reports.utils.csv_formatter import (
                write_timely_one_header,
                format_currency,
                format_date_pt,
                translate_column_names,
            )

            # Cabeçalho bonito com branding TimelyOne
            write_timely_one_header(writer, "Relatórios Básicos", start, end)

            # Bloco de resumo com nomes traduzidos
            writer.writerow(["📈 RESUMO EXECUTIVO"])
            writer.writerow([])
            writer.writerow(
                [
                    "Agendamentos Totais",
                    "Agendamentos Concluídos",
                    "Receita Total",
                    "Ticket Médio",
                ]
            )
            writer.writerow(
                [
                    int(total_count or 0),
                    int(done_count or 0),
                    format_currency(revenue),
                    format_currency(avg_ticket),
                ]
            )

            # Espaçamento
            writer.writerow([])
            writer.writerow([])

            # Série temporal
            writer.writerow(["📊 RECEITA DIÁRIA"])
            writer.writerow([])

            # Cabeçalhos traduzidos para série temporal
            headers = ["Data", "Receita"]
            # translate_column_names espera um dict, não uma lista
            headers_dict = {header: header for header in headers}
            translated_headers_dict = translate_column_names(headers_dict)
            translated_headers = list(translated_headers_dict.values())
            writer.writerow(translated_headers)

            # Dados da série
            for row in series_qs:
                writer.writerow(
                    [
                        format_date_pt(row["bucket"]),
                        format_currency(row["revenue"] or 0),
                    ]
                )

            # Preparar resposta
            csv_content = buffer.getvalue()
            buffer.close()

            response = HttpResponse(csv_content, content_type="text/csv; charset=utf-8")
            filename = f"relatorios_basicos_{start.strftime('%Y%m%d')}_{end.strftime('%Y%m%d')}.csv"
            response["Content-Disposition"] = f'attachment; filename="{filename}"'

            return response

        except Exception as e:
            logger.error(f"Error generating basic reports CSV: {e}")
            return Response(
                {"error": "Erro ao gerar CSV dos relatórios básicos."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


@extend_schema(
    tags=["Reports"],
    summary="Relatórios Avançados - Disponível apenas para planos Pro e Enterprise",
    parameters=[PARAM_FROM, PARAM_TO, PARAM_LIMIT, PARAM_OFFSET, PARAM_INTERVAL],
    responses={
        200: {
            "type": "object",
            "properties": {
                "top_services": {"type": "object"},
                "revenue": {"type": "object"},
            },
        },
        403: OpenApiTypes.OBJECT,
    },
)
class RetentionReportView(_BaseReports):
    throttle_classes = (PerUserScopedRateThrottle,)
    throttle_scope = "reports"

    def get_permissions(self):
        return [
            IsAuthenticated(),
            RequiresProReports(),
        ]

    @cache_drf_response(
        prefix="reports:retention:json",
        ttl=settings.REPORTS_CACHE_TTL.get("retention_json", 300),
        vary_on_params=["from", "to"],
        vary_on_user=True,
        view_label="retention",
        format_label="json",
    )
    @extend_schema(
        tags=["Reports"],
        summary="Retenção de Clientes (Novos vs Recorrentes)",
        parameters=[PARAM_FROM, PARAM_TO],
        responses={
            200: {
                "type": "object",
                "properties": {
                    "new_clients": {
                        "type": "object",
                        "properties": {
                            "qty": {"type": "integer"},
                            "revenue": {"type": "number"},
                        },
                    },
                    "returning_clients": {
                        "type": "object",
                        "properties": {
                            "qty": {"type": "integer"},
                            "revenue": {"type": "number"},
                        },
                    },
                    "period": {
                        "type": "object",
                        "properties": {
                            "start": {"type": "string", "format": "date-time"},
                            "end": {"type": "string", "format": "date-time"},
                        },
                    },
                },
            },
            403: OpenApiTypes.OBJECT,
        },
    )
    @observe_request(endpoint="/api/reports/retention/")
    def get(self, request):
        start, end = _date_range(request)
        date_gte = {f"{DATE_FIELD}__gte": start}
        date_lte = {f"{DATE_FIELD}__lte": end}

        qs = Appointment.objects.filter(
            **date_gte,
            **date_lte,
            status__in=COMPLETED_STATUSES,
            tenant=getattr(request.user, "tenant", None),
        )

        # Anota se é novo cliente (criado dentro do range)
        qs = qs.annotate(
            is_new_client=Case(
                When(customer__created_at__gte=start, then=Value(True)),
                default=Value(False),
                output_field=BooleanField(),
            )
        )

        # Agrega
        price_expr = Sum(APPT_PRICE_FIELD) if APPT_PRICE_FIELD else _price_sum()
        metrics = qs.values("is_new_client").annotate(
            count=Count("id"), revenue=price_expr
        )

        new_clients = {"qty": 0, "revenue": 0}
        returning_clients = {"qty": 0, "revenue": 0}

        for m in metrics:
            if m["is_new_client"]:
                new_clients["qty"] = m["count"]
                new_clients["revenue"] = m["revenue"] or 0
            else:
                returning_clients["qty"] = m["count"]
                returning_clients["revenue"] = m["revenue"] or 0

        return Response(
            {
                "new_clients": new_clients,
                "returning_clients": returning_clients,
                "period": {"start": start, "end": end},
            }
        )


class AdvancedReportsView(APIView):
    """
    Endpoint para relatórios avançados.
    Disponível apenas para plano Pro.
    """

    permission_classes = [IsAuthenticated, RequiresProReports]
    throttle_classes = (PerUserScopedRateThrottle,)
    throttle_scope = "reports"

    @observe_request(endpoint="/api/reports/advanced/")
    def get(self, request):
        """Retorna relatórios avançados: top services, revenue e retention"""

        # Reutiliza a lógica das views existentes
        top_services_view = TopServicesReportView()
        top_services_view.request = request
        top_services_response = top_services_view.get(request)

        revenue_view = RevenueSeriesReportView()
        revenue_view.request = request
        revenue_response = revenue_view.get(request)

        retention_view = RetentionReportView()
        retention_view.request = request
        retention_response = retention_view.get(request)

        return Response(
            {
                "top_services": (
                    top_services_response.data
                    if hasattr(top_services_response, "data")
                    else top_services_response.content
                ),
                "revenue": (
                    revenue_response.data
                    if hasattr(revenue_response, "data")
                    else revenue_response.content
                ),
                "retention": (
                    retention_response.data
                    if hasattr(retention_response, "data")
                    else retention_response.content
                ),
            }
        )


class ExportAdvancedReportsCSVView(_BaseReports):
    """
    GET /api/reports/advanced/export/?from=YYYY-MM-DD&to=YYYY-MM-DD&interval=day|week|month

    Gera CSV com relatórios avançados combinados:
      - Seção Top Services (serviço, agendamentos, receita, preço médio)
      - Seção Revenue Series (período, agendamentos, receita, ticket médio)
    """

    permission_classes = [IsAuthenticated, RequiresProReports]
    throttle_classes = (PerUserScopedRateThrottle,)
    throttle_scope = "export_csv"

    @cache_drf_response(
        prefix="reports:advanced:csv",
        ttl=settings.REPORTS_CACHE_TTL.get("advanced_csv", 300),  # 5 min default
        vary_on_params=["from", "to", "interval"],
        vary_on_user=True,
        view_label="advanced",
        format_label="csv",
    )
    @extend_schema(
        tags=["Reports"],
        summary="Exportar Relatórios Avançados (CSV)",
        parameters=[PARAM_FROM, PARAM_TO, PARAM_INTERVAL],
        responses={200: RESP_CSV_OVERVIEW, 403: OpenApiTypes.OBJECT},
    )
    @observe_request(endpoint="/api/reports/advanced/export/")
    def get(self, request) -> HttpResponse:
        """Exporta relatórios avançados em CSV"""

        try:
            start, end = _date_range(request)
            interval = request.query_params.get("interval", "day")
            tenant = getattr(request.user, "tenant", None)

            date_gte = {f"{DATE_FIELD}__gte": start}
            date_lte = {f"{DATE_FIELD}__lte": end}

            # === TOP SERVICES DATA ===
            top_services_qs = Appointment.objects.filter(
                **date_gte,
                **date_lte,
                status__in=COMPLETED_STATUSES,
                tenant=tenant,
            ).values("service_id", "service__name")

            if APPT_PRICE_FIELD:
                top_services_qs = top_services_qs.annotate(
                    qty=Count("id"), revenue=Sum(APPT_PRICE_FIELD)
                )
            else:
                top_services_qs = top_services_qs.annotate(
                    qty=Count("id"), revenue=_price_sum()
                )

            top_services_qs = top_services_qs.order_by(
                "-qty", "-revenue", "service__name"
            )

            # === REVENUE SERIES DATA ===
            from django.db.models.functions import TruncDay, TruncWeek, TruncMonth

            trunc = {"day": TruncDay, "week": TruncWeek, "month": TruncMonth}.get(
                interval, TruncDay
            )

            revenue_qs = (
                Appointment.objects.filter(
                    **date_gte,
                    **date_lte,
                    status__in=COMPLETED_STATUSES,
                    tenant=tenant,
                )
                .annotate(bucket=trunc(DATE_FIELD))
                .values("bucket")
                .annotate(appointment_count=Count("id"), revenue=_price_sum())
                .order_by("bucket")
            )

            # === GENERATE CSV ===
            buffer = io.StringIO()
            writer = csv.writer(buffer)

            # Importar utilitários de formatação
            from reports.utils.csv_formatter import (
                write_timely_one_header,
                format_currency,
                format_date_pt,
                translate_column_names,
            )

            # Cabeçalho bonito com branding TimelyOne
            write_timely_one_header(writer, "Relatórios Avançados", start, end)

            # === SEÇÃO TOP SERVICES ===
            writer.writerow(["🏆 TOP SERVIÇOS"])
            writer.writerow([])

            # Cabeçalhos traduzidos para top services
            top_services_headers = translate_column_names(
                {
                    "service_name": "Serviço",
                    "qty": "Agendamentos",
                    "revenue": "Receita",
                    "avg_price": "Preço Médio",
                }
            )
            writer.writerow(list(top_services_headers.values()))

            # Dados dos top services
            for row in top_services_qs.iterator(chunk_size=1000):
                qty = row["qty"] or 0
                revenue = row["revenue"] or 0
                avg_price = (revenue / qty) if qty > 0 else 0

                writer.writerow(
                    [
                        row["service__name"],
                        qty,
                        format_currency(revenue),
                        format_currency(avg_price),
                    ]
                )

            # Espaçamento entre seções
            writer.writerow([])
            writer.writerow([])

            # === SEÇÃO REVENUE SERIES ===
            writer.writerow([f"📊 RECEITA POR {interval.upper()}"])
            writer.writerow([])

            # Cabeçalhos traduzidos para revenue series
            revenue_headers = translate_column_names(
                {
                    "period": "Período",
                    "appointments": "Agendamentos",
                    "revenue": "Receita",
                    "avg_ticket": "Ticket Médio",
                }
            )
            writer.writerow(list(revenue_headers.values()))

            # Dados da revenue series
            for row in revenue_qs.iterator(chunk_size=1000):
                appointment_count = row["appointment_count"] or 0
                revenue = row["revenue"] or 0
                avg_ticket = (
                    (revenue / appointment_count) if appointment_count > 0 else 0
                )

                dt = row["bucket"]
                writer.writerow(
                    [
                        format_date_pt(dt) if hasattr(dt, "isoformat") else str(dt),
                        appointment_count,
                        format_currency(revenue),
                        format_currency(avg_ticket),
                    ]
                )

            # Preparar resposta
            csv_content = buffer.getvalue()
            buffer.close()

            response = HttpResponse(csv_content, content_type="text/csv; charset=utf-8")
            filename = f"relatorios_avancados_{interval}_{start.strftime('%Y%m%d')}_{end.strftime('%Y%m%d')}.csv"
            response["Content-Disposition"] = f'attachment; filename="{filename}"'
            response["X-Content-Type-Options"] = "nosniff"
            response["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
            response["Pragma"] = "no-cache"

            logger.info(
                f"Advanced reports CSV export completed successfully. Period: {start.date()} to {end.date()}, Interval: {interval}"
            )
            return response

        except Exception as e:
            logger.error(f"Error generating advanced reports CSV: {e}", exc_info=True)
            return Response(
                {"error": "Erro ao gerar CSV dos relatórios avançados."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
