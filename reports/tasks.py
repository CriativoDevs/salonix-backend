import csv
import io
import logging
import os

from celery import shared_task
from django.conf import settings
from django.db.models import Count, Sum, F
from django.db.models.functions import TruncDay, TruncWeek, TruncMonth
from django.utils import timezone

from reports.models import ExportJob

logger = logging.getLogger("reports")

COMPLETED_STATUSES = ("completed", "paid")


def _parse_params(parameters: dict):
    """Resolve start/end datetimes a partir dos parametros do job."""
    from datetime import timedelta

    now = timezone.now()
    to_str = parameters.get("to")
    from_str = parameters.get("from")

    end = _parse_iso(to_str) or now
    start = _parse_iso(from_str) or (end - timedelta(days=30))
    return start, end


def _parse_iso(s):
    if not s:
        return None
    dt = timezone.datetime.fromisoformat(s)
    if dt.tzinfo is None:
        return timezone.make_aware(dt)
    return dt


def _price_sum():
    from core.models import Appointment
    from django.db.models import DecimalField

    preferred = {"price", "price_eur", "amount", "amount_eur", "total_price"}
    for f in Appointment._meta.fields:
        if isinstance(f, DecimalField) and f.name in preferred:
            return Sum(f.name)
    return Sum(F("service__price_eur"))


def _date_filter(start, end):
    from core.models import Appointment
    from django.db import models as dj_models

    preferred = {"created_at", "date", "start", "start_at", "start_time"}
    dt_fields = [
        f for f in Appointment._meta.fields if isinstance(f, dj_models.DateTimeField)
    ]
    by_name = [f for f in dt_fields if f.name in preferred]
    field = by_name[0].name if by_name else (dt_fields[0].name if dt_fields else "created_at")
    return {f"{field}__gte": start, f"{field}__lte": end}


def _save_csv(job: ExportJob, content: str) -> str:
    """Grava o CSV em disco e retorna o caminho relativo ao MEDIA_ROOT."""
    tenant_slug = job.tenant.slug if hasattr(job.tenant, "slug") else str(job.tenant_id)
    rel_dir = os.path.join("exports", tenant_slug)
    abs_dir = os.path.join(settings.MEDIA_ROOT, rel_dir)
    os.makedirs(abs_dir, exist_ok=True)

    filename = f"{job.report_type}_{job.id}.csv"
    rel_path = os.path.join(rel_dir, filename)
    abs_path = os.path.join(settings.MEDIA_ROOT, rel_path)

    with open(abs_path, "w", encoding="utf-8", newline="") as f:
        f.write(content)

    return rel_path


# ── CSV generators ────────────────────────────────────────────────────────────

def _generate_basic(tenant, start, end) -> str:
    from core.models import Appointment
    from reports.utils.csv_formatter import (
        write_timely_one_header,
        format_currency,
        format_date_pt,
    )

    date_f = _date_filter(start, end)
    qs = Appointment.objects.filter(**date_f, tenant=tenant)
    total = qs.count()
    done_qs = qs.filter(status__in=COMPLETED_STATUSES)
    done = done_qs.count()
    revenue = done_qs.aggregate(total=_price_sum())["total"] or 0
    avg_ticket = (revenue / done) if done else 0

    series_qs = (
        done_qs.annotate(bucket=TruncDay(list(_date_filter(start, end).keys())[0].split("__")[0]))
        .values("bucket")
        .annotate(revenue=_price_sum())
        .order_by("bucket")
    )

    buf = io.StringIO()
    w = csv.writer(buf)
    write_timely_one_header(w, "Relatórios Básicos", start, end)
    w.writerow(["📈 RESUMO EXECUTIVO"])
    w.writerow([])
    w.writerow(["Agendamentos Totais", "Agendamentos Concluídos", "Receita Total", "Ticket Médio"])
    w.writerow([int(total), int(done), format_currency(float(revenue)), format_currency(float(avg_ticket))])
    w.writerow([])
    w.writerow(["📊 RECEITA DIÁRIA"])
    w.writerow([])
    w.writerow(["Data", "Receita"])
    for row in series_qs.iterator(chunk_size=1000):
        w.writerow([format_date_pt(row["bucket"]), format_currency(row["revenue"] or 0)])

    return buf.getvalue()


def _generate_top_services(tenant, start, end) -> str:
    from core.models import Appointment
    from reports.utils.csv_formatter import write_timely_one_header, format_currency

    date_f = _date_filter(start, end)
    qs = (
        Appointment.objects.filter(**date_f, status__in=COMPLETED_STATUSES, tenant=tenant)
        .values("service_id", "service__name")
        .annotate(qty=Count("id"), revenue=_price_sum())
        .order_by("-qty", "-revenue", "service__name")
    )

    buf = io.StringIO()
    w = csv.writer(buf)
    write_timely_one_header(w, "Relatório Top Serviços", start, end)
    w.writerow(["🏆 TOP SERVIÇOS"])
    w.writerow([])
    w.writerow(["ID do Serviço", "Nome do Serviço", "Quantidade", "Receita"])
    for row in qs.iterator(chunk_size=1000):
        w.writerow([row["service_id"], row["service__name"], row["qty"] or 0, format_currency(row["revenue"] or 0)])

    return buf.getvalue()


def _generate_revenue(tenant, start, end, interval: str = "day") -> str:
    from core.models import Appointment
    from reports.utils.csv_formatter import write_timely_one_header, format_currency, format_date_pt

    trunc = {"day": TruncDay, "week": TruncWeek, "month": TruncMonth}.get(interval, TruncDay)
    date_f = _date_filter(start, end)
    field_name = list(date_f.keys())[0].split("__")[0]

    qs = (
        Appointment.objects.filter(**date_f, status__in=COMPLETED_STATUSES, tenant=tenant)
        .annotate(bucket=trunc(field_name))
        .values("bucket")
        .annotate(revenue=_price_sum())
        .order_by("bucket")
    )

    buf = io.StringIO()
    w = csv.writer(buf)
    write_timely_one_header(w, f"Relatório de Receita ({interval.title()})", start, end)
    w.writerow([f"📊 RECEITA POR {interval.upper()}"])
    w.writerow([])
    w.writerow(["Período", "Receita"])
    for row in qs.iterator(chunk_size=1000):
        dt = row["bucket"]
        w.writerow([format_date_pt(dt) if hasattr(dt, "isoformat") else str(dt), format_currency(row["revenue"] or 0)])

    return buf.getvalue()


def _generate_advanced(tenant, start, end, interval: str = "day") -> str:
    from core.models import Appointment
    from reports.utils.csv_formatter import (
        write_timely_one_header,
        format_currency,
        format_date_pt,
    )

    trunc = {"day": TruncDay, "week": TruncWeek, "month": TruncMonth}.get(interval, TruncDay)
    date_f = _date_filter(start, end)
    field_name = list(date_f.keys())[0].split("__")[0]

    top_qs = (
        Appointment.objects.filter(**date_f, status__in=COMPLETED_STATUSES, tenant=tenant)
        .values("service_id", "service__name")
        .annotate(qty=Count("id"), revenue=_price_sum())
        .order_by("-qty", "-revenue", "service__name")
    )

    rev_qs = (
        Appointment.objects.filter(**date_f, status__in=COMPLETED_STATUSES, tenant=tenant)
        .annotate(bucket=trunc(field_name))
        .values("bucket")
        .annotate(appointment_count=Count("id"), revenue=_price_sum())
        .order_by("bucket")
    )

    buf = io.StringIO()
    w = csv.writer(buf)
    write_timely_one_header(w, "Relatórios Avançados", start, end)

    w.writerow(["🏆 TOP SERVIÇOS"])
    w.writerow([])
    w.writerow(["ID do Serviço", "Nome do Serviço", "Quantidade", "Receita"])
    for row in top_qs.iterator(chunk_size=1000):
        w.writerow([row["service_id"], row["service__name"], row["qty"] or 0, format_currency(row["revenue"] or 0)])

    w.writerow([])
    w.writerow([f"📊 RECEITA POR {interval.upper()}"])
    w.writerow([])
    w.writerow(["Período", "Agendamentos", "Receita"])
    for row in rev_qs.iterator(chunk_size=1000):
        dt = row["bucket"]
        w.writerow([
            format_date_pt(dt) if hasattr(dt, "isoformat") else str(dt),
            row["appointment_count"] or 0,
            format_currency(row["revenue"] or 0),
        ])

    return buf.getvalue()


@shared_task(name="reports.cleanup_expired_export_jobs")
def cleanup_expired_export_jobs():
    expired = ExportJob.objects.filter(expires_at__lte=timezone.now())
    deleted_files = 0
    deleted_jobs = 0

    for job in expired.iterator(chunk_size=200):
        if job.file_path:
            abs_path = os.path.join(settings.MEDIA_ROOT, job.file_path)
            try:
                os.remove(abs_path)
                deleted_files += 1
            except FileNotFoundError:
                pass
        job.delete()
        deleted_jobs += 1

    logger.info(
        "export_cleanup_done",
        extra={"deleted_jobs": deleted_jobs, "deleted_files": deleted_files},
    )
    return {"deleted_jobs": deleted_jobs, "deleted_files": deleted_files}


_GENERATORS = {
    ExportJob.ReportType.BASIC: _generate_basic,
    ExportJob.ReportType.TOP_SERVICES: _generate_top_services,
    ExportJob.ReportType.REVENUE: _generate_revenue,
    ExportJob.ReportType.ADVANCED: _generate_advanced,
}


# ── Task ──────────────────────────────────────────────────────────────────────

@shared_task(name="reports.generate_csv_export", bind=True, max_retries=3)
def generate_csv_export(self, job_id: str):
    try:
        job = ExportJob.objects.select_related("tenant").get(id=job_id)
    except ExportJob.DoesNotExist:
        logger.error("export_job_not_found", extra={"job_id": job_id})
        return

    job.status = ExportJob.Status.PROCESSING
    job.save(update_fields=["status", "updated_at"])

    try:
        start, end = _parse_params(job.parameters)
        interval = job.parameters.get("interval", "day")
        generator = _GENERATORS.get(job.report_type)

        if generator is None:
            raise ValueError(f"Tipo de report desconhecido: {job.report_type}")

        # Revenue e advanced aceitam interval; basic e top_services não
        if job.report_type in (ExportJob.ReportType.REVENUE, ExportJob.ReportType.ADVANCED):
            content = generator(job.tenant, start, end, interval)
        else:
            content = generator(job.tenant, start, end)

        rel_path = _save_csv(job, content)

        job.status = ExportJob.Status.DONE
        job.file_path = rel_path
        job.save(update_fields=["status", "file_path", "updated_at"])

        logger.info(
            "export_job_done",
            extra={"job_id": job_id, "report_type": job.report_type, "file": rel_path},
        )

    except Exception as exc:
        logger.error(
            "export_job_failed",
            extra={"job_id": job_id, "error": str(exc)},
            exc_info=True,
        )
        job.status = ExportJob.Status.FAILED
        job.error_message = str(exc)
        job.save(update_fields=["status", "error_message", "updated_at"])
        raise self.retry(exc=exc, countdown=60)
