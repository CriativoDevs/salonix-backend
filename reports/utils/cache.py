from __future__ import annotations

from functools import wraps
from typing import Callable, Iterable, Optional, Dict, Any, List
from django.core.cache import cache

import logging
import threading
import time

logger = logging.getLogger("reports")

# --- Debounce infra (process-local) -----------------------------------------
# Observação: isto coalesce invalidações dentro do MESMO processo.
# Em ambiente com múltiplos workers/processos, ainda é útil (reduz tempestade local),
# mas não coordena entre processos (para isso, daria para usar um lock em Redis).
_DEBOUNCE_LOCK = threading.Lock()
_DEBOUNCE_TIMERS: Dict[str, threading.Timer] = {}


def _debounced(prefix: str, wait_s: float, fn: Callable[[], None]) -> None:
    """Agenda 'fn' para rodar após 'wait_s', cancelando um timer pendente do mesmo prefixo."""
    with _DEBOUNCE_LOCK:
        existing = _DEBOUNCE_TIMERS.get(prefix)
        if existing and existing.is_alive():
            existing.cancel()
        t = threading.Timer(wait_s, fn)
        _DEBOUNCE_TIMERS[prefix] = t
        t.daemon = True
        t.start()


# ---------------------------------------------------------------------------


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
    from django.http import HttpResponse

    def decorator(view_func: Callable):
        @wraps(view_func)
        def wrapper(self, request, *args, **kwargs):
            user_id = (
                request.user.id
                if (vary_on_user and getattr(request, "user", None))
                else None
            )
            params = request.query_params

            key = _build_cache_key(
                prefix=prefix,
                user_id=user_id,
                params=params,
                vary_on_params=vary_on_params or (),
            )

            cached = cache.get(key)
            if cached:
                resp = HttpResponse(
                    cached.get("content", b""),
                    status=cached.get("status", 200),
                    content_type=cached.get("content_type")
                    or "application/octet-stream",
                )
                for h, v in (cached.get("headers") or {}).items():
                    if h.lower() != "content-type":
                        resp[h] = v
                return resp

            response = view_func(self, request, *args, **kwargs)

            def _extract_headers(r):
                return {
                    k: v
                    for k, v in r.items()
                    if k.lower()
                    in {
                        "content-disposition",
                        "x-total-count",
                        "x-limit",
                        "x-offset",
                        "link",
                    }
                }

            if (
                hasattr(response, "add_post_render_callback")
                and getattr(response, "status_code", 200) == 200
            ):

                def _store(rendered_response):
                    payload = {
                        "status": rendered_response.status_code,
                        "content": getattr(rendered_response, "rendered_content", b""),
                        "content_type": rendered_response.get("Content-Type"),
                        "headers": _extract_headers(rendered_response),
                    }
                    cache.set(key, payload, ttl)
                    return rendered_response

                response.add_post_render_callback(_store)
                return response

            from django.http import HttpResponse as DjangoHttpResponse

            if (
                isinstance(response, DjangoHttpResponse)
                and getattr(response, "status_code", 200) == 200
            ):
                payload = {
                    "status": response.status_code,
                    "content": response.content,
                    "content_type": response.get("Content-Type"),
                    "headers": _extract_headers(response),
                }
                cache.set(key, payload, ttl)
                return response

            return response

        return wrapper

    return decorator


def invalidate_cache(prefix: str) -> int:
    """
    Remove todas as chaves cujo nome contenha `prefix`.
    Retorna a quantidade (estimada) de chaves removidas.
    """
    removed = 0
    try:
        if cache.__class__.__module__.startswith("django_redis"):
            pattern = f"*{prefix}*"
            try:
                removed = cache.delete_pattern(pattern)
            except Exception:
                client = cache.client.get_client(write=True)
                count = 0
                for key in client.scan_iter(match=pattern, count=1000):
                    client.delete(key)
                    count += 1
                removed = count
        else:
            inner = getattr(cache, "_cache", None)
            if isinstance(inner, dict):
                to_del = [k for k in list(inner.keys()) if prefix in str(k)]
                for k in to_del:
                    try:
                        del inner[k]
                        removed += 1
                    except KeyError:
                        pass
            else:
                logger.warning(
                    "invalidate_cache: backend %s não suporta varredura; no-op.",
                    cache.__class__.__name__,
                )
                return 0

        logger.info(
            "invalidate_cache_ok prefix=%s backend=%s removed=%s",
            prefix,
            cache.__class__.__name__,
            removed,
        )
        return removed

    except Exception:
        logger.exception(
            "invalidate_cache_error prefix=%s backend=%s",
            prefix,
            cache.__class__.__name__,
        )
        return removed


def invalidate_many(prefixes: Iterable[str]) -> int:
    """Inválida uma lista de prefixos e retorna o total somado."""
    total = 0
    for p in prefixes:
        total += invalidate_cache(p)
    return total


def debounce_invalidate(prefix: str, wait_seconds: float = 2.0) -> None:
    """
    Coalesce de invalidações do mesmo prefixo dentro de 'wait_seconds'.
    (process-local; útil para bursts).
    """

    def _run():
        try:
            invalidate_cache(prefix)
        except Exception:
            logger.exception("debounce_invalidate_error prefix=%s", prefix)

    _debounced(prefix, wait_seconds, _run)


def debounce_invalidate_many(
    prefixes: Iterable[str], wait_seconds: float = 2.0
) -> None:
    """Versão *many* do debounce: agenda cada prefixo separadamente."""
    for p in set(prefixes):
        debounce_invalidate(p, wait_seconds)
