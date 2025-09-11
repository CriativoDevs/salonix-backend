# reports/throttling.py
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.settings import api_settings


class PerUserScopedRateThrottle(ScopedRateThrottle):
    """
    Igual ao ScopedRateThrottle, mas chaveia por usuário autenticado (user.id)
    e respeita o throttle_scope definido na View. Cai para IP se anônimo.
    """

    # DRF chama sem parâmetros
    def get_rate(self):
        # self.scope já foi setado em allow_request() pelo DRF
        rates = api_settings.DEFAULT_THROTTLE_RATES or {}
        return rates.get(self.scope)

    def get_cache_key(self, request, view):
        # garante que self.scope esteja setado (por segurança)
        if not getattr(self, "scope", None):
            self.scope = getattr(view, self.scope_attr, None)
        if self.scope is None:
            return None

        # per-user quando autenticado; senão IP
        if request.user and request.user.is_authenticated:
            ident = str(request.user.pk)
        else:
            ident = self.get_ident(request)

        return self.cache_format % {"scope": self.scope, "ident": ident}
