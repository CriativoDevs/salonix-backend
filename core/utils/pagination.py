from typing import Tuple, List
from urllib.parse import urlencode, urlparse, parse_qs, urlunparse

from rest_framework.exceptions import ValidationError


def get_limit_offset(request, default: int = 20, max_limit: int = 100) -> Tuple[int, int]:
    qp = getattr(request, "query_params", None) or getattr(request, "GET", {})

    limit_raw = qp.get("limit")
    offset_raw = qp.get("offset")

    try:
        limit = int(limit_raw) if limit_raw is not None else int(default)
    except (TypeError, ValueError):
        raise ValidationError({"limit": ["Deve ser um inteiro válido."]})

    try:
        offset = int(offset_raw) if offset_raw is not None else 0
    except (TypeError, ValueError):
        raise ValidationError({"offset": ["Deve ser um inteiro válido."]})

    if limit <= 0:
        raise ValidationError({"limit": ["Deve ser maior que 0."]})
    if offset < 0:
        raise ValidationError({"offset": ["Deve ser maior ou igual a 0."]})

    if limit > max_limit:
        limit = max_limit

    return limit, offset


def _update_query(url: str, new_params: dict) -> str:
    parsed = urlparse(url)
    existing = parse_qs(parsed.query, keep_blank_values=True)
    for k, v in new_params.items():
        existing[k] = [str(v)]
    query = urlencode(existing, doseq=True)
    return urlunparse(
        (parsed.scheme, parsed.netloc, parsed.path, parsed.params, query, parsed.fragment)
    )


def _build_link(url: str, rel: str) -> str:
    return f"<{url}>; rel=\"{rel}\""


def set_pagination_headers(response, request, total_count: int, limit: int, offset: int):
    response["X-Total-Count"] = str(total_count)
    response["X-Limit"] = str(limit)
    response["X-Offset"] = str(offset)

    links: List[str] = []
    base_url = request.build_absolute_uri()

    # next
    if offset + limit < total_count:
        next_offset = offset + limit
        next_url = _update_query(base_url, {"limit": limit, "offset": next_offset})
        links.append(_build_link(next_url, "next"))

    # prev
    if offset > 0:
        prev_offset = max(0, offset - limit)
        prev_url = _update_query(base_url, {"limit": limit, "offset": prev_offset})
        links.append(_build_link(prev_url, "prev"))

    if links:
        response["Link"] = ", ".join(links)

    return response