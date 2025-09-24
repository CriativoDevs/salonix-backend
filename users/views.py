import logging

from django.core.cache import cache
from rest_framework import generics, status
from rest_framework.generics import RetrieveUpdateAPIView
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.views import TokenObtainPairView

from drf_spectacular.utils import extend_schema

from rest_framework.exceptions import NotFound

from salonix_backend.error_handling import TenantError, ErrorCodes
from .models import UserFeatureFlags, Tenant

from .serializers import (
    EmailTokenObtainPairSerializer,
    TenantMetaSerializer,
    TenantBrandingUpdateSerializer,
    UserRegistrationSerializer,
    UserFeatureFlagsSerializer,
    UserFeatureFlagsUpdateSerializer,
    TenantSelfServiceSerializer,
)


bootstrap_logger = logging.getLogger("users.bootstrap")


def _me_tenant_cache_key(user_id: int, tenant_id: int, tenant_updated_at):
    updated_ts = "0"
    if tenant_updated_at:
        try:
            updated_ts = str(int(tenant_updated_at.timestamp()))
        except Exception:  # pragma: no cover - fallback caso timestamp falhe
            updated_ts = tenant_updated_at.isoformat()
    return f"users:me-tenant:{user_id}:{tenant_id}:{updated_ts}"


class UserRegistrationView(generics.CreateAPIView):
    serializer_class = UserRegistrationSerializer
    permission_classes = [AllowAny]


class MeFeatureFlagsView(RetrieveUpdateAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = UserFeatureFlagsSerializer  # default para GET

    def get_object(self):
        flags, _ = UserFeatureFlags.objects.get_or_create(user=self.request.user)
        return flags

    def get_serializer_class(self):
        if self.request.method in ("PATCH", "PUT"):
            return UserFeatureFlagsUpdateSerializer
        return UserFeatureFlagsSerializer


class EmailTokenObtainPairView(TokenObtainPairView):
    serializer_class = EmailTokenObtainPairSerializer


class TenantMetaView(APIView):
    """
    GET /api/users/tenant/meta/
    PATCH /api/users/tenant/meta/

    Endpoint público para obter metadados do tenant (branding + feature flags).
    Aceita tenant via query parameter 'tenant' ou header 'X-Tenant-Slug'.

    PATCH requer autenticação e permite atualizar branding (logo, cores).
    """

    def get_permissions(self):
        """Permissões dinâmicas: público para GET, autenticado para PATCH"""
        if self.request.method == "GET":
            return [AllowAny()]
        return [IsAuthenticated()]

    def get_tenant(self, request):
        """Obter tenant baseado no request"""
        # Para GET: usar query param ou header
        if request.method == "GET":
            tenant_slug = request.GET.get("tenant") or request.headers.get(
                "X-Tenant-Slug"
            )
            if not tenant_slug:
                raise TenantError(
                    "Parâmetro 'tenant' ou header 'X-Tenant-Slug' é obrigatório",
                    code=ErrorCodes.VALIDATION_REQUIRED_FIELD,
                )
        else:
            # Para PATCH: usar tenant do usuário autenticado
            if not hasattr(request.user, "tenant") or not request.user.tenant:
                raise TenantError(
                    "Usuário não possui tenant associado",
                    code=ErrorCodes.BUSINESS_TENANT_NOT_FOUND,
                )
            return request.user.tenant

        try:
            return Tenant.objects.get(slug=tenant_slug, is_active=True)
        except Tenant.DoesNotExist:
            raise TenantError(
                f"Tenant '{tenant_slug}' não encontrado ou inativo",
                code=ErrorCodes.BUSINESS_TENANT_NOT_FOUND,
            )

    @extend_schema(responses=TenantMetaSerializer)
    def get(self, request):
        """Retornar metadados do tenant especificado"""
        # TenantError será tratado automaticamente pelo custom_exception_handler
        tenant = self.get_tenant(request)

        # Serializar dados do tenant
        serializer = TenantMetaSerializer(tenant)
        return Response(serializer.data, status=status.HTTP_200_OK)

    @extend_schema(
        request=TenantBrandingUpdateSerializer,
        responses=TenantMetaSerializer,
    )
    def patch(self, request):
        """Atualizar branding do tenant (logo, cores)"""
        try:
            tenant = self.get_tenant(request)
        except ValueError as e:
            return Response(
                {"detail": str(e)},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Verificar se o usuário é dono do tenant
        if request.user.tenant != tenant:
            return Response(
                {"detail": "Você não tem permissão para alterar este tenant."},
                status=status.HTTP_403_FORBIDDEN,
            )

        # Serializar e validar dados
        serializer = TenantBrandingUpdateSerializer(
            tenant, data=request.data, partial=True
        )
        if serializer.is_valid():
            # Limpar logo anterior se novo logo for enviado
            from typing import Any, Dict, cast

            vdata = cast(Dict[str, Any], serializer.validated_data)
            if vdata.get("logo"):
                if tenant.logo:
                    tenant.logo.delete(save=False)  # Não salvar ainda
                # Limpar logo_url se logo for enviado
                vdata["logo_url"] = None

            serializer.save()

            # Retornar dados atualizados
            response_serializer = TenantMetaSerializer(tenant)
            return Response(response_serializer.data, status=status.HTTP_200_OK)

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class MeTenantView(APIView):
    permission_classes = [IsAuthenticated]
    CACHE_TTL = 30

    def get(self, request):
        user = request.user
        tenant = getattr(user, "tenant", None)
        if getattr(user, "is_ops_user", False) or not tenant:
            raise NotFound("Tenant não encontrado para o usuário autenticado.")

        cache_key = _me_tenant_cache_key(user.id, tenant.id, tenant.updated_at)
        payload = cache.get(cache_key)
        cached_hit = payload is not None

        if not cached_hit:
            payload = TenantSelfServiceSerializer(tenant).data
            cache.set(cache_key, payload, timeout=self.CACHE_TTL)

        bootstrap_logger.info(
            "Tenant bootstrap entregue",
            extra={
                "event": "tenant_bootstrap",
                "user_id": user.id,
                "user_email": getattr(user, "email", ""),
                "tenant_id": tenant.id,
                "tenant_slug": tenant.slug,
                "cached": cached_hit,
            },
        )

        return Response(payload, status=status.HTTP_200_OK)
