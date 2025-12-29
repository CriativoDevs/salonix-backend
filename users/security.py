import logging
from typing import Optional

from django.conf import settings
from rest_framework.exceptions import ValidationError
from captcha.models import CaptchaStore

logger = logging.getLogger("users.security")


def _get_captcha_data_from_request(request) -> tuple[Optional[str], Optional[str]]:
    """
    Extrai a chave e o valor do captcha da requisição.
    """
    key = request.data.get("captcha_key") if hasattr(request, "data") else None
    value = request.data.get("captcha_value") if hasattr(request, "data") else None

    if not key:
        key = request.headers.get("X-Captcha-Key")
    if not value:
        value = request.headers.get("X-Captcha-Value")

    return key, value


def enforce_captcha_or_raise(request) -> None:
    """
    Valida captcha conforme flags em settings.

    Regras:
    - Se CAPTCHA_ENABLED = false -> no-op
    - Se CAPTCHA_BYPASS_TOKEN definido e igual ao valor recebido -> aceita (bypass para testes)
    - Caso contrário, valida junto ao CaptchaStore (django-simple-captcha)
    """
    if not getattr(settings, "CAPTCHA_ENABLED", False):
        return

    key, value = _get_captcha_data_from_request(request)

    # Lógica de Bypass (antes de validar key)
    bypass_token = getattr(settings, "CAPTCHA_BYPASS_TOKEN", "")
    if bypass_token and value == bypass_token:
        logger.info(
            "Captcha bypass aceito",
            extra={
                "bypass": True,
            },
        )
        return

    # Se não tem key/value, erro imediato
    if not key or not value:
        raise ValidationError({"captcha": ["Token de captcha ausente."]})

    # Validação Real (Local)
    try:
        # Tenta recuperar o registro do CaptchaStore
        # A validação de case-insensitive já é feita pelo método response.lower() == challenge.lower()
        # Mas aqui usaremos o manager para verificar e deletar após uso
        captcha = CaptchaStore.objects.get(hashkey=key)

        # Verifica expiração
        # O CaptchaStore já tem um método de cleanup, mas precisamos garantir validade

        if captcha.response.lower() == value.lower():
            # Sucesso! Marca como usado (remove do banco para não reutilizar)
            captcha.delete()
            return
        else:
            raise ValidationError({"captcha": ["Captcha incorreto."]})

    except CaptchaStore.DoesNotExist:
        raise ValidationError({"captcha": ["Captcha inválido ou expirado."]})
    except ValidationError:
        # Se for um ValidationError lançado acima, relança
        raise
    except Exception as e:
        logger.error("Erro na validação do captcha", extra={"error": str(e)})
        raise ValidationError({"captcha": ["Erro ao validar captcha."]})
