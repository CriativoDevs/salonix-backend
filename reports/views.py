# reports/views.py
from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework import status

from django.db.models import Sum, Count, F
from django.utils import timezone
from django.db import models

from core.models import Appointment
from users.models import UserFeatureFlags
from datetime import timedelta

COMPLETED_STATUSES = ("completed", "paid")


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


def _date_range(request):
    to = request.query_params.get("to")
    frm = request.query_params.get("from")
    now = timezone.now()
    end = timezone.make_aware(timezone.datetime.fromisoformat(to)) if to else now
    start = (
        timezone.make_aware(timezone.datetime.fromisoformat(frm))
        if frm
        else end - timedelta(days=30)
    )
    return start, end


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
    throttle_scope = "reports"

    def _guard(self, request):
        ff, _ = UserFeatureFlags.objects.get_or_create(user=request.user)
        if not (ff.is_pro and ff.reports_enabled):
            return Response({"detail": "Módulo de relatórios desativado."}, status=403)


class OverviewReportView(_BaseReports):
    def get(self, request):
        denied = self._guard(request)
        if denied:
            return denied
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
    def get(self, request):
        denied = self._guard(request)
        if denied:
            return denied
        start, end = _date_range(request)
        limit = int(request.query_params.get("limit", 10))
        date_gte = {f"{DATE_FIELD}__gte": start}
        date_lte = {f"{DATE_FIELD}__lte": end}

        qs = Appointment.objects.filter(
            **date_gte, **date_lte, status__in=COMPLETED_STATUSES
        ).values("service_id", "service__name")

        if APPT_PRICE_FIELD:
            qs = qs.annotate(qty=Count("id"), revenue=Sum(APPT_PRICE_FIELD))
        else:
            qs = qs.annotate(qty=Count("id"), revenue=Sum(F(SERVICE_PRICE_LOOKUP)))

        qs = qs.order_by("-qty")[:limit]

        data = [
            {
                "service_id": r["service_id"],
                "service_name": r["service__name"],
                "qty": r["qty"],
                "revenue": r["revenue"] or 0,
            }
            for r in qs
        ]
        return Response(data)


class RevenueReportView(_BaseReports):
    def get(self, request):
        denied = self._guard(request)
        if denied:
            return denied
        start, end = _date_range(request)
        interval = request.query_params.get("interval", "day")
        from django.db.models.functions import TruncDay, TruncWeek, TruncMonth

        trunc = {"day": TruncDay, "week": TruncWeek, "month": TruncMonth}.get(
            interval, TruncDay
        )
        date_gte = {f"{DATE_FIELD}__gte": start}
        date_lte = {f"{DATE_FIELD}__lte": end}

        base_qs = (
            Appointment.objects.filter(
                **date_gte, **date_lte, status__in=COMPLETED_STATUSES
            )
            .annotate(bucket=trunc(DATE_FIELD))
            .values("bucket")
        )

        if APPT_PRICE_FIELD:
            qs = base_qs.annotate(revenue=Sum(APPT_PRICE_FIELD)).order_by("bucket")
        else:
            qs = base_qs.annotate(revenue=Sum(F(SERVICE_PRICE_LOOKUP))).order_by(
                "bucket"
            )

        data = [{"period_start": r["bucket"], "revenue": r["revenue"] or 0} for r in qs]
        return Response({"interval": interval, "series": data})
