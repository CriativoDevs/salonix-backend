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

    Endpoint público para obter metadados do tenant (branding + feature flags).
    Aceita tenant via query parameter 'tenant' ou header 'X-Tenant-Slug'.
    """

    permission_classes = [AllowAny]

    def get(self, request):
        """Retornar metadados do tenant especificado"""
        # Obter slug do tenant via query param ou header
        tenant_slug = request.GET.get("tenant") or request.headers.get("X-Tenant-Slug")

        if not tenant_slug:
            return Response(
                {
                    "detail": "Parâmetro 'tenant' ou header 'X-Tenant-Slug' é obrigatório."
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            # Buscar tenant ativo
            tenant = Tenant.objects.get(slug=tenant_slug, is_active=True)
        except Tenant.DoesNotExist:
            return Response(
                {"detail": f"Tenant '{tenant_slug}' não encontrado ou inativo."},
                status=status.HTTP_404_NOT_FOUND,
            )

        # Serializar dados do tenant
        serializer = TenantMetaSerializer(tenant)
        return Response(serializer.data, status=status.HTTP_200_OK)
