from rest_framework.throttling import ScopedRateThrottle
from rest_framework.settings import api_settings


class _BaseUsersThrottle(ScopedRateThrottle):
    def get_rate(self):
        rates = api_settings.DEFAULT_THROTTLE_RATES or {}
        return rates.get(self.scope)

    def get_cache_key(self, request, view):
        if not getattr(self, "scope", None):
            self.scope = getattr(view, self.scope_attr, None)
        if self.scope is None:
            return None
        if request.user and request.user.is_authenticated:
            ident = str(request.user.pk)
        else:
            ident = self.get_ident(request)
        return self.cache_format % {"scope": self.scope, "ident": ident}


class UsersAuthLoginThrottle(_BaseUsersThrottle):
    scope = "auth_login"


class UsersAuthRegisterThrottle(_BaseUsersThrottle):
    scope = "auth_register"


class UsersTenantMetaPublicThrottle(_BaseUsersThrottle):
    scope = "tenant_meta_public"
