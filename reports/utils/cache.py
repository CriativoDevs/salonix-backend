# reports/utils/cache.py
from __future__ import annotations

from functools import wraps
from typing import Callable, Iterable, Optional, Dict, Any
from django.core.cache import cache


def _build_cache_key(
    *,
    prefix: str,
    user_id: Optional[int],
    params: Dict[str, Any],
    vary_on_params: Iterable[str],
) -> str:
    parts = [prefix]
    if user_id is not None:
        parts.append(f"user:{user_id}")
    # somente os params declarados (ordem estável)
    if vary_on_params:
        selected = []
        for name in vary_on_params:
            val = params.get(name)
            selected.append(f"{name}={val}")
        parts.append("&".join(selected))
    return ":".join(parts)


def cache_drf_response(
    *,
    prefix: str,
    ttl: int,
    vary_on_params: Iterable[str] = (),
    vary_on_user: bool = False,
    view_label: str = "",
    format_label: str = "",
) -> Callable:
    """
    Cacheia respostas DRF sem tocar no Response antes do render.

    - Se houver cache: retorna HttpResponse construído a partir do payload renderizado.
    - Se não houver: executa a view e registra um post_render_callback para gravar no cache.

    A chave considera:
      - prefix
      - user_id (se vary_on_user=True)
      - apenas os parâmetros listados em vary_on_params (ex.: from, to, limit, offset...)

    O objeto salvo no cache é um dicionário:
      {
        "status": int,
        "content": bytes,
        "content_type": str,
        "headers": dict[str,str]   # somente cabeçalhos simples
      }
    """
    from django.http import HttpResponse

    def decorator(view_func: Callable):
        @wraps(view_func)
        def wrapper(self, request, *args, **kwargs):
            user_id = (
                request.user.id
                if (vary_on_user and getattr(request, "user", None))
                else None
            )

            # DRF expõe query_params como QueryDict
            params = request.query_params

            key = _build_cache_key(
                prefix=prefix,
                user_id=user_id,
                params=params,
                vary_on_params=vary_on_params or (),
            )

            cached = cache.get(key)
            if cached:
                # Reconstrói HttpResponse simples (já renderizado)
                resp = HttpResponse(
                    cached.get("content", b""),
                    status=cached.get("status", 200),
                    content_type=cached.get("content_type")
                    or "application/octet-stream",
                )
                # re-aplica alguns headers básicos (sem sobrescrever Content-Type)
                for h, v in (cached.get("headers") or {}).items():
                    if h.lower() != "content-type":
                        resp[h] = v
                return resp

            # Cache miss -> executa a view normalmente
            response = view_func(self, request, *args, **kwargs)

            # Somente cacheia respostas "cacheáveis" (200 OK, sem StreamingHttpResponse)
            if (
                hasattr(response, "add_post_render_callback")
                and getattr(response, "status_code", 200) == 200
            ):

                def _store(rendered_response):
                    # Agora já está renderizado -> podemos ler rendered_content e cabeçalhos
                    payload = {
                        "status": rendered_response.status_code,
                        "content": getattr(rendered_response, "rendered_content", b""),
                        "content_type": rendered_response.get("Content-Type"),
                        # Cabeçalhos úteis (evite cabeçalhos voláteis)
                        "headers": {
                            k: v
                            for k, v in rendered_response.items()
                            if k.lower()
                            in {
                                "content-disposition",
                                "x-total-count",
                                "x-limit",
                                "x-offset",
                            }
                        },
                    }
                    cache.set(key, payload, ttl)
                    return rendered_response

                response.add_post_render_callback(_store)

            return response

        return wrapper

    return decorator
