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


class UsersStaffInviteThrottle(_BaseUsersThrottle):
    scope = "users_staff_invite"


class UsersStaffResendInviteThrottle(_BaseUsersThrottle):
    scope = "users_staff_resend"


class UsersPasswordResetThrottle(_BaseUsersThrottle):
    scope = "users_password_reset"


class UsersClientAccessLinkThrottle(_BaseUsersThrottle):
    scope = "clients_access_link"

    def get_cache_key(self, request, view):
        # Per cliente+tenant quando disponíveis, senão padrão
        tenant_slug = None
        email = None
        try:
            tenant_slug = (
                request.data.get("tenant_slug") if hasattr(request, "data") else None
            )
            email = request.data.get("email") if hasattr(request, "data") else None
        except Exception:
            tenant_slug = None
            email = None

        if tenant_slug and email:
            ident = f"{str(tenant_slug).lower()}:{str(email).strip().lower()}"
            return self.cache_format % {"scope": self.scope, "ident": ident}

        return super().get_cache_key(request, view)


class FeedbackCreateThrottle(_BaseUsersThrottle):
    scope = "feedback_create"

    def get_cache_key(self, request, view):
        tenant_slug = None
        email = None
        customer_id = None
        try:
            tenant_slug = (
                request.data.get("tenant_slug") if hasattr(request, "data") else None
            )
            email = request.data.get("email") if hasattr(request, "data") else None
            customer_id = (
                request.data.get("customer") if hasattr(request, "data") else None
            )
        except Exception:
            tenant_slug = None
            email = None
            customer_id = None

        # Se houver tenant+email, chave por combinação
        if tenant_slug and email:
            ident = f"{str(tenant_slug).lower()}:{str(email).strip().lower()}"
            return self.cache_format % {"scope": self.scope, "ident": ident}

        # Se houver tenant no request e customer_id, chave por tenant_id:customer_id
        tenant_id = getattr(getattr(request, "tenant", None), "id", None)
        if tenant_id and customer_id:
            try:
                ident = f"{int(tenant_id)}:{int(customer_id)}"
                return self.cache_format % {"scope": self.scope, "ident": ident}
            except Exception:
                pass

        if tenant_id and getattr(
            getattr(request, "user", None), "is_authenticated", False
        ):
            try:
                ident = f"{int(tenant_id)}:{int(request.user.pk)}"
                return self.cache_format % {"scope": self.scope, "ident": ident}
            except Exception:
                pass

        return super().get_cache_key(request, view)
