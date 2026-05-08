"""
Backfill routine for DailyReportAggregate.

Usage (management command or shell):
    from reports.backfill import run_backfill
    run_backfill()                          # all tenants, all history
    run_backfill(tenant=t, since=date(2024,1,1))
"""
import logging
from datetime import date, timedelta

from django.db import transaction
from django.db.models import Count, Sum

from core.models import Appointment
from reports.models import DailyReportAggregate
from users.models import Tenant

logger = logging.getLogger("reports")

COMPLETED_STATUSES = ("completed", "paid")


def _aggregate_day(tenant_id: int, day: date) -> dict:
    qs = Appointment.objects.filter(tenant_id=tenant_id, slot__start_time__date=day)
    total = qs.count()
    done_qs = qs.filter(status__in=COMPLETED_STATUSES)
    agg = done_qs.aggregate(
        completed=Count("id"),
        revenue=Sum("service__price_eur"),
    )
    return {
        "appointments_total": total,
        "appointments_completed": agg["completed"] or 0,
        "revenue_total": agg["revenue"] or 0,
    }


def backfill_tenant(tenant_id: int, since: date | None = None, until: date | None = None):
    """Recalcula agregados diários para um tenant no intervalo [since, until]."""
    if until is None:
        until = date.today() - timedelta(days=1)
    if since is None:
        first = (
            Appointment.objects.filter(tenant_id=tenant_id)
            .order_by("slot__start_time")
            .values_list("slot__start_time__date", flat=True)
            .first()
        )
        if first is None:
            return
        since = first

    day = since
    created = updated = 0
    while day <= until:
        data = _aggregate_day(tenant_id, day)
        _, is_new = DailyReportAggregate.objects.update_or_create(
            tenant_id=tenant_id,
            date=day,
            defaults=data,
        )
        if is_new:
            created += 1
        else:
            updated += 1
        day += timedelta(days=1)

    logger.info(
        "backfill_tenant_done",
        extra={"tenant_id": tenant_id, "since": since, "until": until, "rows_created": created, "rows_updated": updated},
    )
    return {"created": created, "updated": updated}


def run_backfill(tenant: Tenant | None = None, since: date | None = None, until: date | None = None):
    """Executa backfill para todos os tenants (ou um específico)."""
    tenants = [tenant] if tenant else list(Tenant.objects.filter(is_active=True))
    results = {}
    for t in tenants:
        with transaction.atomic():
            results[t.id] = backfill_tenant(t.id, since=since, until=until)
    return results
