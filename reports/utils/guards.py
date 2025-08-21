from functools import wraps


def require_reports_enabled(view_func):
    """
    Garante 403 antecipado para usuários sem acesso aos relatórios,
    evitando cache/observability/throttle para esses casos.
    """

    @wraps(view_func)
    def _wrapped(self, request, *args, **kwargs):
        denied = getattr(self, "_guard")(request)
        if denied:
            return denied
        return view_func(self, request, *args, **kwargs)

    return _wrapped
