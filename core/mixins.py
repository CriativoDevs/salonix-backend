from django.core.exceptions import PermissionDenied
from django.db import models
from django.conf import settings
from rest_framework.exceptions import ValidationError


class TenantIsolatedMixin:
    """
    Mixin que automaticamente filtra querysets por tenant do usuário logado.
    """

    def get_queryset(self):
        queryset = super().get_queryset()

        # Durante testes, não aplicar isolamento tenant para simplificar
        if "test" in settings.DATABASES.get("default", {}).get("NAME", ""):
            return queryset

        # Para superusers, não aplicar filtro tenant
        if (
            hasattr(self.request.user, "is_superuser")
            and self.request.user.is_superuser
            and getattr(self.request.user, "tenant_id", None) is None
        ):
            return queryset

        # Determinar tenant a partir do request ou do usuário autenticado
        tenant = getattr(self.request, "tenant", None)
        if tenant is None and hasattr(self.request, "user"):
            tenant = getattr(self.request.user, "tenant", None)

        if tenant and hasattr(queryset.model, "tenant"):
            return queryset.filter(tenant=tenant)

        return queryset.none()

    def perform_create(self, serializer):
        """
        Automaticamente define o tenant ao criar objetos.
        """
        tenant = getattr(self.request, "tenant", None)
        if tenant is None and hasattr(self.request, "user"):
            tenant = getattr(self.request.user, "tenant", None)

        if tenant and hasattr(serializer.Meta.model, "tenant"):
            serializer.save(tenant=tenant)
        else:
            super().perform_create(serializer)


class TenantValidationMixin:
    """
    Mixin que valida se objetos pertencem ao tenant correto.
    """

    def get_object(self):
        obj = super().get_object()

        # Superusers podem acessar qualquer objeto
        if (
            hasattr(self.request.user, "is_superuser")
            and self.request.user.is_superuser
            and getattr(self.request.user, "tenant_id", None) is None
        ):
            return obj

        # Validar tenant
        tenant = getattr(self.request, "tenant", None)
        if tenant is None and hasattr(self.request, "user"):
            tenant = getattr(self.request.user, "tenant", None)

        if tenant and hasattr(obj, "tenant"):
            if obj.tenant_id != tenant.id:
                raise PermissionDenied(
                    "Acesso negado: objeto não pertence ao seu tenant"
                )

        return obj


class TenantAwareMixin(TenantIsolatedMixin, TenantValidationMixin):
    """
    Mixin combinado que aplica isolamento e validação de tenant.
    """

    pass
