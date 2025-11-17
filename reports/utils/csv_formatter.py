"""
Utilitários para formatação de CSV com branding TimelyOne
"""

import csv
from datetime import datetime
from typing import Any, Optional


def write_timely_one_header(
    writer: csv.writer,
    report_title: str,
    start_date: Any,
    end_date: Any,
    additional_info: Optional[str] = None,
) -> None:
    """
    Escreve cabeçalho bonito com branding TimelyOne

    Args:
        writer: csv.writer object
        report_title: Título do relatório
        start_date: Data inicial
        end_date: Data final
        additional_info: Informação adicional (ex: intervalo)
    """
    # Cabeçalho compacto com branding
    writer.writerow(["═════════════════════════════════════════════════"])
    writer.writerow(["TimelyOne - Sistema de Gestão"])
    writer.writerow(["═════════════════════════════════════════════════"])

    # Informações do relatório em formato compacto
    writer.writerow([f"📊 RELATÓRIO: {report_title.upper()}"])
    writer.writerow([f"📅 PERÍODO: {format_date_range(start_date, end_date)}"])
    writer.writerow([f"🕐 GERADO EM: {datetime.now().strftime('%d/%m/%Y às %H:%M')}"])
    writer.writerow(["═════════════════════════════════════════════════"])
    writer.writerow([])


def format_date_range(start_date: Any, end_date: Any) -> str:
    """
    Formata range de datas de forma amigável
    """

    def format_single_date(date_obj):
        if date_obj is None:
            return "N/A"
        if hasattr(date_obj, "date"):
            return date_obj.date().strftime("%d/%m/%Y")
        elif hasattr(date_obj, "strftime"):
            return date_obj.strftime("%d/%m/%Y")
        else:
            return str(date_obj)

    start_str = format_single_date(start_date)
    end_str = format_single_date(end_date)

    return f"{start_str} até {end_str}"


def format_currency(value: float) -> str:
    """
    Formata valor monetário em euros
    """
    if value is None:
        return "€ 0,00"
    return f"€ {value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def format_percentage(value: float) -> str:
    """
    Formata percentual
    """
    if value is None:
        return "0,0%"
    return f"{value:.1f}%".replace(".", ",")


def format_date_pt(date_obj: Any) -> str:
    """
    Formata data no padrão brasileiro
    """
    if date_obj is None:
        return ""
    if hasattr(date_obj, "date"):
        return date_obj.date().strftime("%d/%m/%Y")
    elif hasattr(date_obj, "strftime"):
        return date_obj.strftime("%d/%m/%Y")
    else:
        return str(date_obj)


def format_datetime_pt(datetime_obj: Any) -> str:
    """
    Formata data e hora no padrão brasileiro
    """
    if datetime_obj is None:
        return ""
    if hasattr(datetime_obj, "strftime"):
        return datetime_obj.strftime("%d/%m/%Y %H:%M")
    else:
        return str(datetime_obj)


def translate_column_names(columns: dict) -> dict:
    """
    Traduz nomes de colunas para português
    """
    translations = {
        # Overview
        "appointments_total": "Total de Agendamentos",
        "appointments_completed": "Agendamentos Concluídos",
        "revenue_total": "Receita Total",
        "avg_ticket": "Ticket Médio",
        "period_start": "Data",
        "revenue": "Receita",
        # Top Services
        "appointments_count": "Quantidade de Agendamentos",
        "total_revenue": "Receita Total",
        # Revenue
        "period": "Período",
        "total": "Total",
        # Appointments
        "id": "ID",
        "client_name": "Nome do Cliente",
        "client_email": "Email do Cliente",
        "service_name": "Serviço",
        "professional_name": "Profissional",
        "slot_start_time": "Início",
        "slot_end_time": "Fim",
        "status": "Status",
        "notes": "Observações",
        "created_at": "Criado em",
    }

    return {translations.get(k, k): v for k, v in columns.items()}


def write_summary_footer(writer: csv.writer, summary_data: dict) -> None:
    """
    Escreve rodapé com resumo/totais
    """
    writer.writerow([])
    writer.writerow(["═══════════════════════════════════════════════════════════"])
    writer.writerow(["                        RESUMO"])
    writer.writerow(["═══════════════════════════════════════════════════════════"])

    for key, value in summary_data.items():
        if isinstance(value, float) and "receita" in key.lower():
            formatted_value = format_currency(value)
        elif isinstance(value, float) and "%" in key:
            formatted_value = format_percentage(value)
        else:
            formatted_value = str(value)

        writer.writerow([f"{key}: {formatted_value}"])

    writer.writerow([])
    writer.writerow(["═══════════════════════════════════════════════════════════"])
    writer.writerow(["                   Gerado por TimelyOne"])
    writer.writerow(["═══════════════════════════════════════════════════════════"])
