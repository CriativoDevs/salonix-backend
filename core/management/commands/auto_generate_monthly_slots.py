"""
Management command BE-SLOTS-04 (#559).

Gera automaticamente os slots do próximo mês para tenants que ativaram
`Tenant.auto_generate_slots_enabled`, reaproveitando a mesma lógica de
serviço usada por `ScheduleSlotViewSet.bulk_generate` (core/services/slots.py)
para não duplicar regras de negócio.

Celery Beat está confirmado inativo em produção (ver issue #559) — este
command deve ser agendado manualmente como Cron Job no dashboard do Railway,
por exemplo 1x/mês:

    python manage.py auto_generate_monthly_slots

Escolha de design: `interval_minutes` fixo em 30 (não há campo de intervalo
padrão no model `Professional` hoje); se um dia for necessário um intervalo
por profissional, introduzir o campo e passar a lê-lo aqui.
"""

import zoneinfo
from datetime import datetime

from django.core.management.base import BaseCommand
from django.utils import timezone

from core.models import Professional, ScheduleSlot
from core.services.slots import build_slot_intervals, resolve_dates_for_period
from users.models import Tenant, TenantBusinessHours

DEFAULT_INTERVAL_MINUTES = 30


class Command(BaseCommand):
    help = (
        "Gera os slots do próximo mês para tenants com "
        "auto_generate_slots_enabled=True. Idempotente — não duplica slots "
        "já existentes. Agendar via Cron Job no Railway (Celery Beat está "
        "inativo em produção)."
    )

    def handle(self, *args, **options):
        self.stdout.write("Iniciando geração automática de slots mensais...")

        today = timezone.localdate()
        # Próximo mês a partir de hoje.
        if today.month == 12:
            next_month_base = today.replace(year=today.year + 1, month=1, day=1)
        else:
            next_month_base = today.replace(month=today.month + 1, day=1)

        tenants_processed = 0
        tenants_skipped_no_business_hours = 0
        total_created = 0

        tenants = Tenant.objects.filter(
            is_active=True, auto_generate_slots_enabled=True
        )

        for tenant in tenants.iterator():
            bh_qs = TenantBusinessHours.objects.filter(
                tenant=tenant, is_active=True
            )
            if not bh_qs.exists():
                tenants_skipped_no_business_hours += 1
                self.stdout.write(
                    self.style.WARNING(
                        f"Tenant {tenant.slug!r} ({tenant.id}) sem horário de "
                        "funcionamento configurado — pulado."
                    )
                )
                continue

            bh_by_day = {bh.day_of_week: bh for bh in bh_qs}
            dates = resolve_dates_for_period(next_month_base, "month")
            tz = zoneinfo.ZoneInfo(tenant.timezone or "Europe/Lisbon")

            professionals = Professional.objects.filter(
                tenant=tenant, is_active=True
            )

            tenant_created = 0
            for professional in professionals:
                period_start = datetime.combine(
                    dates[0], datetime.min.time()
                ).replace(tzinfo=tz)
                period_end = datetime.combine(
                    dates[-1], datetime.max.time()
                ).replace(tzinfo=tz)
                existing_starts = set(
                    ScheduleSlot.objects.filter(
                        tenant=tenant,
                        professional=professional,
                        start_time__gte=period_start,
                        start_time__lte=period_end,
                    ).values_list("start_time", flat=True)
                )

                slots_to_create = []
                pending_starts = set()

                for day in dates:
                    bh = bh_by_day.get(day.weekday())
                    if not bh:
                        continue
                    intervals = build_slot_intervals(
                        tenant,
                        professional,
                        [day],
                        bh.start_time,
                        bh.end_time,
                        DEFAULT_INTERVAL_MINUTES,
                    )
                    for current, slot_end in intervals:
                        if current in existing_starts or current in pending_starts:
                            continue
                        slots_to_create.append(
                            ScheduleSlot(
                                tenant=tenant,
                                professional=professional,
                                start_time=current,
                                end_time=slot_end,
                                is_available=True,
                                status="available",
                            )
                        )
                        pending_starts.add(current)

                if slots_to_create:
                    ScheduleSlot.objects.bulk_create(slots_to_create)
                    tenant_created += len(slots_to_create)

            total_created += tenant_created
            tenants_processed += 1
            self.stdout.write(
                f"Tenant {tenant.slug!r} ({tenant.id}): {tenant_created} slot(s) criado(s)."
            )

        self.stdout.write(
            self.style.SUCCESS(
                f"Geração automática concluída: {tenants_processed} tenant(s) "
                f"processado(s), {tenants_skipped_no_business_hours} pulado(s) "
                f"por falta de horário de funcionamento, {total_created} "
                "slot(s) criado(s) no total."
            )
        )
