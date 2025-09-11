"""
Utilitário para geração de arquivos .ics (iCalendar) para agendamentos.
"""

import hashlib
from datetime import datetime, timedelta, timezone as dt_timezone
from django.utils import timezone
from typing import Dict, Any, cast

from core.models import Appointment


class ICSGenerator:
    """Gerador de arquivos .ics para agendamentos."""

    @staticmethod
    def generate_ics(appointment: Appointment) -> str:
        """
        Gerar conteúdo .ics para um agendamento.

        Args:
            appointment: Instância do agendamento

        Returns:
            String com conteúdo .ics formatado
        """
        # UID único baseado no tenant + appointment ID
        uid = ICSGenerator._generate_uid(appointment)

        # Dados do agendamento
        start_time = appointment.slot.start_time
        end_time = appointment.slot.end_time

        # Garantir que temos datetime objects (não strings dos testes)
        if isinstance(start_time, str):
            # Fallback para testes - assumir formato ISO
            try:
                s = cast(str, start_time)
                start_time = datetime.fromisoformat(s.replace("Z", "+00:00"))
            except Exception:
                start_time = timezone.now()

        if isinstance(end_time, str):
            try:
                e = cast(str, end_time)
                end_time = datetime.fromisoformat(e.replace("Z", "+00:00"))
            except Exception:
                end_time = start_time + timedelta(hours=1)

        # Converter para UTC se necessário
        if start_time.tzinfo is None:
            start_time = timezone.make_aware(start_time)
        if end_time.tzinfo is None:
            end_time = timezone.make_aware(end_time)

        # Formato iCalendar requer UTC
        start_utc = start_time.astimezone(dt_timezone.utc)
        end_utc = end_time.astimezone(dt_timezone.utc)

        # Informações do agendamento
        summary = f"{appointment.service.name} - {appointment.professional.name}"
        description = ICSGenerator._build_description(appointment)
        location = ICSGenerator._build_location(appointment)

        # Data de criação
        created = appointment.created_at
        if created.tzinfo is None:
            created = timezone.make_aware(created)
        created_utc = created.astimezone(dt_timezone.utc)

        # Timestamp atual para DTSTAMP
        now_utc = timezone.now().astimezone(dt_timezone.utc)

        # Construir conteúdo .ics
        ics_content = [
            "BEGIN:VCALENDAR",
            "VERSION:2.0",
            "PRODID:-//Salonix//Appointment//EN",
            "CALSCALE:GREGORIAN",
            "METHOD:PUBLISH",
            "BEGIN:VEVENT",
            f"UID:{uid}",
            f"DTSTART:{start_utc.strftime('%Y%m%dT%H%M%SZ')}",
            f"DTEND:{end_utc.strftime('%Y%m%dT%H%M%SZ')}",
            f"DTSTAMP:{now_utc.strftime('%Y%m%dT%H%M%SZ')}",
            f"CREATED:{created_utc.strftime('%Y%m%dT%H%M%SZ')}",
            f"SUMMARY:{summary}",
            f"DESCRIPTION:{description}",
        ]

        if location:
            ics_content.append(f"LOCATION:{location}")

        # Status baseado no status do agendamento
        status = ICSGenerator._get_ics_status(cast(str, appointment.status))
        ics_content.append(f"STATUS:{status}")

        # Finalizar evento
        ics_content.extend(
            [
                "BEGIN:VALARM",
                "TRIGGER:-PT30M",  # Lembrete 30 minutos antes
                "ACTION:DISPLAY",
                f"DESCRIPTION:Lembrete: {summary} em 30 minutos",
                "END:VALARM",
                "END:VEVENT",
                "END:VCALENDAR",
            ]
        )

        return "\r\n".join(ics_content)

    @staticmethod
    def _generate_uid(appointment: Appointment) -> str:
        """Gerar UID único para o evento."""
        # Usar tenant ID + appointment ID para garantir unicidade
        tenant_id = appointment.tenant.id if appointment.tenant else "default"
        base_string = f"{tenant_id}-{appointment.id}-appointment"

        # Hash para garantir formato consistente
        hash_obj = hashlib.md5(base_string.encode())
        return f"{hash_obj.hexdigest()}@salonix.app"

    @staticmethod
    def _build_description(appointment: Appointment) -> str:
        """Construir descrição detalhada do agendamento."""
        lines = [
            f"Serviço: {appointment.service.name}",
            f"Profissional: {appointment.professional.name}",
        ]

        # Adicionar preço se disponível
        if hasattr(appointment.service, "price_eur") and appointment.service.price_eur:
            lines.append(f"Preço: €{appointment.service.price_eur:.2f}")

        # Adicionar duração se disponível
        if (
            hasattr(appointment.service, "duration_minutes")
            and appointment.service.duration_minutes
        ):
            lines.append(f"Duração: {appointment.service.duration_minutes} minutos")

        # Adicionar notas se houver
        if appointment.notes and appointment.notes.strip():
            lines.append(f"Notas: {appointment.notes}")

        # Adicionar informações do salão
        if appointment.tenant:
            lines.append(f"Salão: {appointment.tenant.name}")

        return "\\n".join(lines)  # Escape para formato .ics

    @staticmethod
    def _build_location(appointment: Appointment) -> str:
        """Construir localização do evento."""
        if appointment.tenant and appointment.tenant.name:
            return appointment.tenant.name
        return ""

    @staticmethod
    def _get_ics_status(appointment_status: str) -> str:
        """Converter status do agendamento para status .ics."""
        status_mapping = {
            "scheduled": "CONFIRMED",
            "completed": "CONFIRMED",
            "paid": "CONFIRMED",
            "cancelled": "CANCELLED",
            "no_show": "CANCELLED",
        }
        return status_mapping.get(appointment_status, "TENTATIVE")

    @staticmethod
    def get_filename(appointment: Appointment) -> str:
        """Gerar nome de arquivo apropriado."""
        # Data do agendamento
        start_time = appointment.slot.start_time
        if isinstance(start_time, str):
            try:
                s = cast(str, start_time)
                start_time = datetime.fromisoformat(s.replace("Z", "+00:00"))
            except Exception:
                start_time = timezone.now()

        if hasattr(start_time, "strftime"):
            date_str = start_time.strftime("%Y%m%d")
        else:
            date_str = timezone.now().strftime("%Y%m%d")

        # Nome limpo do serviço
        service_name = appointment.service.name.replace(" ", "_").replace("/", "_")

        return f"agendamento_{service_name}_{date_str}.ics"
