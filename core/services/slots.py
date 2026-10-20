"""
Serviço compartilhado de cálculo de ranges/intervalos de ScheduleSlot.

Usado tanto por `ScheduleSlotViewSet.bulk_generate` (geração de slots
disponíveis dentro do horário de funcionamento) quanto por
`ScheduleSlotViewSet.bulk_block` (bloqueio de intervalos, independente de
horário de funcionamento) em `core/views.py`.
"""

import zoneinfo
from datetime import date as date_type, datetime, time as time_type, timedelta


def resolve_dates_for_period(base_date: date_type, period: str) -> list[date_type]:
    """
    Dado uma data base e um período ("day"|"week"|"month"), devolve a lista
    de datas (date objects) a processar.

    - "day": só `base_date`.
    - "week": semana (segunda a domingo) que contém `base_date`.
    - "month": todos os dias do mês de `base_date`.
    """
    if period == "day":
        return [base_date]
    if period == "week":
        monday = base_date - timedelta(days=base_date.weekday())
        return [monday + timedelta(days=i) for i in range(7)]
    if period == "month":
        first = base_date.replace(day=1)
        if first.month == 12:
            last = first.replace(year=first.year + 1, month=1, day=1) - timedelta(days=1)
        else:
            last = first.replace(month=first.month + 1, day=1) - timedelta(days=1)
        return [first + timedelta(days=i) for i in range((last - first).days + 1)]
    raise ValueError(f"Período inválido: {period!r}")


MAX_BULK_RANGE_DAYS = 92


def resolve_date_range(date_from: date_type, date_to: date_type) -> list[date_type]:
    """Devolve a lista de datas (inclusive) entre `date_from` e `date_to`."""
    if date_to < date_from:
        raise ValueError("date_to deve ser maior ou igual a date_from.")
    span_days = (date_to - date_from).days
    if span_days > MAX_BULK_RANGE_DAYS:
        raise ValueError(
            f"Intervalo máximo permitido é de {MAX_BULK_RANGE_DAYS} dias."
        )
    return [date_from + timedelta(days=i) for i in range(span_days + 1)]


def build_slot_intervals(
    tenant,
    professional,
    dates: list[date_type],
    start_time: time_type,
    end_time: time_type,
    interval_minutes: int,
) -> list[tuple[datetime, datetime]]:
    """
    Para cada dia em `dates`, recorta o intervalo [start_time, end_time) do
    dia em pedaços de `interval_minutes`, devolvendo a lista de tuplas
    `(slot_start, slot_end)` timezone-aware (timezone do `tenant`).

    `professional` é recebido para manter a assinatura alinhada ao domínio
    (slots são sempre por profissional) e para uso futuro por chamadores que
    precisem dele no mesmo ponto de entrada; a função em si não depende de
    nenhum estado do profissional.
    """
    _ = professional  # mantido na assinatura por contexto de domínio
    tz = zoneinfo.ZoneInfo(getattr(tenant, "timezone", None) or "Europe/Lisbon")
    interval = timedelta(minutes=interval_minutes)

    intervals: list[tuple[datetime, datetime]] = []
    for day in dates:
        current = datetime.combine(day, start_time).replace(tzinfo=tz)
        end_dt = datetime.combine(day, end_time).replace(tzinfo=tz)
        while current + interval <= end_dt:
            slot_end = current + interval
            intervals.append((current, slot_end))
            current = slot_end
    return intervals


def compute_gaps(
    window_start: datetime,
    window_end: datetime,
    covered_intervals: list[tuple[datetime, datetime]],
) -> list[tuple[datetime, datetime]]:
    """
    Dado uma janela [window_start, window_end) e uma lista de intervalos já
    cobertos (não necessariamente ordenados/sem overlap), devolve os "gaps":
    os trechos da janela que NÃO estão cobertos por nenhum intervalo.
    """
    normalized = []
    for c_start, c_end in covered_intervals:
        c_start = max(c_start, window_start)
        c_end = min(c_end, window_end)
        if c_start < c_end:
            normalized.append((c_start, c_end))
    normalized.sort()

    gaps = []
    cursor = window_start
    for c_start, c_end in normalized:
        if c_start > cursor:
            gaps.append((cursor, c_start))
        cursor = max(cursor, c_end)
    if cursor < window_end:
        gaps.append((cursor, window_end))
    return gaps


def chunk_interval(
    start: datetime, end: datetime, interval_minutes: int
) -> list[tuple[datetime, datetime]]:
    """Recorta [start, end) em pedaços de `interval_minutes`, descartando resto incompleto."""
    interval = timedelta(minutes=interval_minutes)
    chunks = []
    current = start
    while current + interval <= end:
        chunks.append((current, current + interval))
        current += interval
    return chunks
