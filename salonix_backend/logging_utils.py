"""
Utilitários para logging estruturado do Salonix Backend.
"""

import json
import logging
import uuid
from datetime import datetime
from typing import Any, Dict, Optional


class JSONFormatter(logging.Formatter):
    """
    Formatador JSON estruturado para logs.
    Cria logs em formato JSON para melhor parsing e análise.
    """

    def format(self, record: logging.LogRecord) -> str:
        """Formatar log record como JSON."""
        # Dados base do log
        log_data: Dict[str, Any] = {
            "timestamp": datetime.utcfromtimestamp(record.created).isoformat() + "Z",
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }

        # Adicionar informações de request se disponíveis
        if hasattr(record, "request_id"):
            log_data["request_id"] = record.request_id

        if hasattr(record, "user_id"):
            log_data["user_id"] = record.user_id

        if hasattr(record, "tenant_id"):
            log_data["tenant_id"] = record.tenant_id

        if hasattr(record, "endpoint"):
            log_data["endpoint"] = record.endpoint

        if hasattr(record, "method"):
            log_data["method"] = record.method

        if hasattr(record, "status_code"):
            log_data["status_code"] = record.status_code

        if hasattr(record, "duration_ms"):
            log_data["duration_ms"] = record.duration_ms

        # Adicionar informações de exceção se houver
        if record.exc_info and record.exc_info != (None, None, None):
            exc_type, exc_value, exc_traceback = record.exc_info
            log_data["exception"] = {
                "type": exc_type.__name__ if exc_type else None,
                "message": str(exc_value) if exc_value else None,
                "traceback": (
                    self.formatException(record.exc_info) if exc_traceback else None
                ),
            }

        # Adicionar dados extras do record
        extra_fields = {}
        for key, value in record.__dict__.items():
            if key not in {
                "name",
                "msg",
                "args",
                "levelname",
                "levelno",
                "pathname",
                "filename",
                "module",
                "exc_info",
                "exc_text",
                "stack_info",
                "lineno",
                "funcName",
                "created",
                "msecs",
                "relativeCreated",
                "thread",
                "threadName",
                "processName",
                "process",
                "getMessage",
                "request_id",
                "user_id",
                "tenant_id",
                "endpoint",
                "method",
                "status_code",
                "duration_ms",
            }:
                extra_fields[key] = value

        if extra_fields:
            log_data["extra"] = extra_fields

        return json.dumps(log_data, ensure_ascii=False, default=str)


class DevelopmentFormatter(logging.Formatter):
    """
    Formatador colorido e legível para desenvolvimento.
    """

    # Códigos de cor ANSI
    COLORS = {
        "DEBUG": "\033[36m",  # Ciano
        "INFO": "\033[32m",  # Verde
        "WARNING": "\033[33m",  # Amarelo
        "ERROR": "\033[31m",  # Vermelho
        "CRITICAL": "\033[35m",  # Magenta
        "RESET": "\033[0m",  # Reset
    }

    def format(self, record: logging.LogRecord) -> str:
        """Formatar log record para desenvolvimento."""
        # Cor baseada no nível
        color = self.COLORS.get(record.levelname, "")
        reset = self.COLORS["RESET"]

        # Timestamp formatado
        timestamp = datetime.fromtimestamp(record.created).strftime("%H:%M:%S")

        # Informações base
        base_info = f"{color}[{timestamp}] {record.levelname:<8}{reset}"
        logger_info = f"{record.name:<20}"
        message = record.getMessage()

        # Informações de contexto se disponíveis
        context_parts = []
        if hasattr(record, "request_id"):
            context_parts.append(f"req_id={record.request_id[:8]}")
        if hasattr(record, "user_id"):
            context_parts.append(f"user={record.user_id}")
        if hasattr(record, "tenant_id"):
            context_parts.append(f"tenant={record.tenant_id}")
        if hasattr(record, "endpoint"):
            context_parts.append(f"endpoint={record.endpoint}")

        context_str = f" [{', '.join(context_parts)}]" if context_parts else ""

        # Localização no código
        location = f" ({record.module}:{record.lineno})"

        formatted = f"{base_info} {logger_info} {message}{context_str}{location}"

        # Adicionar traceback se houver exceção
        if record.exc_info:
            formatted += f"\n{self.formatException(record.exc_info)}"

        return formatted


class RequestContextFilter(logging.Filter):
    """
    Filtro para adicionar contexto de request aos logs.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        """Adicionar contexto de request ao log record."""
        # Tentar obter contexto do request atual
        try:
            # Importar aqui para evitar circular imports
            from threading import current_thread

            # Tentar obter request do thread local storage
            thread = current_thread()
            if hasattr(thread, "request"):
                request = thread.request

                # Adicionar informações do request
                if hasattr(request, "request_id"):
                    record.request_id = request.request_id

                if hasattr(request, "user") and request.user.is_authenticated:
                    record.user_id = str(request.user.id)
                    if hasattr(request.user, "tenant") and request.user.tenant:
                        record.tenant_id = request.user.tenant.slug

                if hasattr(request, "path"):
                    record.endpoint = request.path

                if hasattr(request, "method"):
                    record.method = request.method

        except (ImportError, AttributeError):
            # Se não conseguir obter contexto, continua sem ele
            pass

        return True


def get_request_id() -> str:
    """Gerar um ID único para o request."""
    return str(uuid.uuid4())


def setup_logging_context(request):
    """
    Configurar contexto de logging para um request.
    Deve ser chamado no middleware.
    """
    if not hasattr(request, "request_id"):
        request.request_id = get_request_id()

    # Armazenar request no thread local para acesso nos logs
    from threading import current_thread

    current_thread().request = request
