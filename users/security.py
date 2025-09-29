import logging
from typing import Optional

from django.conf import settings
from rest_framework.exceptions import ValidationError

logger = logging.getLogger("users.security")


def _get_captcha_token_from_request(request) -> Optional[str]:
    token = request.data.get("captcha_token") if hasattr(request, "data") else None
    if not token:
        token = request.headers.get("X-Captcha-Token")
    return token


def enforce_captcha_or_raise(request) -> None:
    """
    Valida captcha conforme flags em settings. Em dev/smoke, permite bypass por token.

    Regras:
    - Se CAPTCHA_ENABLED = false -> no-op
    - Se CAPTCHA_BYPASS_TOKEN definido e igual ao token recebido -> aceita
    - Caso contrário, sem integração externa neste contexto offline, rejeita
    """
    if not getattr(settings, "CAPTCHA_ENABLED", False):
        return

    token = _get_captcha_token_from_request(request)
    if not token:
        raise ValidationError({"captcha": ["Token de captcha ausente."]})

    bypass = getattr(settings, "CAPTCHA_BYPASS_TOKEN", "")
    if bypass and token == bypass:
        logger.info(
            "Captcha bypass aceito",
            extra={"provider": getattr(settings, "CAPTCHA_PROVIDER", ""), "bypass": True},
        )
        return

    # Em ambiente offline de testes/CLI, não chamamos provedores externos.
    # Para produção, a integração será via requests.post para o provider.
    logger.warning(
        "Captcha inválido ou não verificado",
        extra={"provider": getattr(settings, "CAPTCHA_PROVIDER", ""), "bypass": False},
    )
    raise ValidationError({"captcha": ["Captcha inválido."]})

