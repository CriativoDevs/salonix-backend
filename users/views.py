from rest_framework import generics, status
from rest_framework.generics import RetrieveUpdateAPIView
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.views import TokenObtainPairView

from .models import UserFeatureFlags, Tenant

from .serializers import (
    EmailTokenObtainPairSerializer,
    TenantMetaSerializer,
    TenantBrandingUpdateSerializer,
    UserRegistrationSerializer,
    UserFeatureFlagsSerializer,
    UserFeatureFlagsUpdateSerializer,
)


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
                raise ValueError(
                    "Parâmetro 'tenant' ou header 'X-Tenant-Slug' é obrigatório."
                )
        else:
            # Para PATCH: usar tenant do usuário autenticado
            if not hasattr(request.user, "tenant") or not request.user.tenant:
                raise ValueError("Usuário não possui tenant associado.")
            return request.user.tenant

        try:
            return Tenant.objects.get(slug=tenant_slug, is_active=True)
        except Tenant.DoesNotExist:
            raise ValueError(f"Tenant '{tenant_slug}' não encontrado ou inativo.")

    def get(self, request):
        """Retornar metadados do tenant especificado"""
        try:
            tenant = self.get_tenant(request)
        except ValueError as e:
            return Response(
                {"detail": str(e)},
                status=(
                    status.HTTP_400_BAD_REQUEST
                    if "obrigatório" in str(e)
                    else status.HTTP_404_NOT_FOUND
                ),
            )

        # Serializar dados do tenant
        serializer = TenantMetaSerializer(tenant)
        return Response(serializer.data, status=status.HTTP_200_OK)

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
            if (
                "logo" in serializer.validated_data
                and serializer.validated_data["logo"]
            ):
                if tenant.logo:
                    tenant.logo.delete(save=False)  # Não salvar ainda
                # Limpar logo_url se logo for enviado
                serializer.validated_data["logo_url"] = None

            serializer.save()

            # Retornar dados atualizados
            response_serializer = TenantMetaSerializer(tenant)
            return Response(response_serializer.data, status=status.HTTP_200_OK)

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
