from django.http import Http404
from django.utils.deprecation import MiddlewareMixin
from users.models import Tenant


class TenantMiddleware(MiddlewareMixin):
    """
    Middleware para identificar o tenant baseado no usuário autenticado.
    Adiciona request.tenant para uso nas views.
    """

    def process_request(self, request):
        request.tenant = None

        if hasattr(request, "user") and request.user.is_authenticated:
            try:
                request.tenant = request.user.tenant
            except AttributeError:
                # Usuário não tem tenant (ex: superuser)
                pass

        return None


class TenantIsolationMiddleware(MiddlewareMixin):
    """
    Middleware para garantir isolamento por tenant em todas as operações.
    Deve ser usado após TenantMiddleware.
    """

    def process_request(self, request):
        # Para APIs que precisam de tenant, verificar se está disponível
        if (
            hasattr(request, "user")
            and request.user.is_authenticated
            and not request.user.is_superuser
            and not getattr(request.user, "is_ops_user", False)
            and not hasattr(request, "tenant")
        ):
            raise Http404("Tenant não encontrado")

        return None
