"""
Helpers para servir dados de reports a partir de DailyReportAggregate
quando possível, com fallback para query direta em Appointment.

Estratégia:
- Dados históricos (até ontem): usa DailyReportAggregate se cobertos.
- Dados de hoje (se no range): query live sobre Appointment.
- Se cobertura incompleta: fallback para query direta no range completo.
"""
from datetime import date, timedelta
from decimal import Decimal

from django.db.models import Count, Sum
from django.db.models.functions import TruncDay, TruncWeek, TruncMonth

COMPLETED_STATUSES = ("completed", "paid")
_TRUNC = {"day": TruncDay, "week": TruncWeek, "month": TruncMonth}


def _is_covered(tenant_id: int, start_date: date, end_date: date) -> bool:
    from reports.models import DailyReportAggregate
    if start_date > end_date:
        return False
    expected = (end_date - start_date).days + 1
    actual = DailyReportAggregate.objects.filter(
        tenant_id=tenant_id, date__gte=start_date, date__lte=end_date
    ).count()
    return actual == expected


def get_overview_data(tenant_id: int, start_dt, end_dt) -> dict:
    """
    Retorna {appointments_total, appointments_completed, revenue_total}.
    Usa agregados para dias históricos; query live para hoje se no range.
    Fallback para query direta se cobertura histórica incompleta.
    """
    from reports.models import DailyReportAggregate
    from core.models import Appointment

    today = date.today()
    start_date = start_dt.date() if hasattr(start_dt, "date") else start_dt
    end_date = end_dt.date() if hasattr(end_dt, "date") else end_dt

    hist_end = min(end_date, today - timedelta(days=1))
    include_today = start_date <= today <= end_date

    total = completed = 0
    revenue = Decimal(0)
    used_agg = False

    if hist_end >= start_date and _is_covered(tenant_id, start_date, hist_end):
        sums = DailyReportAggregate.objects.filter(
            tenant_id=tenant_id, date__gte=start_date, date__lte=hist_end
        ).aggregate(
            t=Sum("appointments_total"),
            c=Sum("appointments_completed"),
            r=Sum("revenue_total"),
        )
        total += sums["t"] or 0
        completed += sums["c"] or 0
        revenue += sums["r"] or 0
        used_agg = True

    if not used_agg:
        qs = Appointment.objects.filter(
            tenant_id=tenant_id,
            slot__start_time__gte=start_dt,
            slot__start_time__lte=end_dt,
        )
        total = qs.count()
        done = qs.filter(status__in=COMPLETED_STATUSES)
        completed = done.count()
        revenue = done.aggregate(r=Sum("service__price_eur"))["r"] or 0
    elif include_today:
        live_qs = Appointment.objects.filter(
            tenant_id=tenant_id,
            slot__start_time__date=today,
            slot__start_time__lte=end_dt,
        )
        total += live_qs.count()
        live_done = live_qs.filter(status__in=COMPLETED_STATUSES)
        completed += live_done.count()
        revenue += live_done.aggregate(r=Sum("service__price_eur"))["r"] or 0

    return {
        "appointments_total": int(total),
        "appointments_completed": int(completed),
        "revenue_total": revenue,
    }


def get_revenue_series(tenant_id: int, start_dt, end_dt, interval: str = "day") -> list:
    """
    Retorna lista de {period_start, revenue, appointment_count}.
    Usa DailyReportAggregate para histórico quando coberto; fallback para Appointment.
    """
    from reports.models import DailyReportAggregate
    from core.models import Appointment

    today = date.today()
    start_date = start_dt.date() if hasattr(start_dt, "date") else start_dt
    end_date = end_dt.date() if hasattr(end_dt, "date") else end_dt

    hist_end = min(end_date, today - timedelta(days=1))
    include_today = start_date <= today <= end_date
    trunc_fn = _TRUNC.get(interval, TruncDay)

    rows = []
    used_agg = False

    if hist_end >= start_date and _is_covered(tenant_id, start_date, hist_end):
        agg_qs = (
            DailyReportAggregate.objects.filter(
                tenant_id=tenant_id, date__gte=start_date, date__lte=hist_end
            )
            .annotate(bucket=trunc_fn("date"))
            .values("bucket")
            .annotate(
                revenue=Sum("revenue_total"),
                appointment_count=Sum("appointments_completed"),
            )
            .order_by("bucket")
        )
        rows = [
            {
                "period_start": r["bucket"],
                "revenue": r["revenue"] or 0,
                "appointment_count": r["appointment_count"] or 0,
            }
            for r in agg_qs
        ]
        used_agg = True

    if not used_agg:
        base = (
            Appointment.objects.filter(
                tenant_id=tenant_id,
                slot__start_time__gte=start_dt,
                slot__start_time__lte=end_dt,
                status__in=COMPLETED_STATUSES,
            )
            .annotate(bucket=trunc_fn("slot__start_time"))
            .values("bucket")
            .annotate(revenue=Sum("service__price_eur"), appointment_count=Count("id"))
            .order_by("bucket")
        )
        rows = [
            {
                "period_start": r["bucket"],
                "revenue": r["revenue"] or 0,
                "appointment_count": r["appointment_count"] or 0,
            }
            for r in base
        ]
    elif include_today:
        today_qs = (
            Appointment.objects.filter(
                tenant_id=tenant_id,
                slot__start_time__date=today,
                slot__start_time__lte=end_dt,
                status__in=COMPLETED_STATUSES,
            )
            .annotate(bucket=trunc_fn("slot__start_time"))
            .values("bucket")
            .annotate(revenue=Sum("service__price_eur"), appointment_count=Count("id"))
        )
        for r in today_qs:
            bucket = r["bucket"]
            existing = next((row for row in rows if row["period_start"] == bucket), None)
            if existing:
                existing["revenue"] += r["revenue"] or 0
                existing["appointment_count"] += r["appointment_count"] or 0
            else:
                rows.append({
                    "period_start": bucket,
                    "revenue": r["revenue"] or 0,
                    "appointment_count": r["appointment_count"] or 0,
                })
        rows.sort(key=lambda x: x["period_start"] or date.min)

    return rows
