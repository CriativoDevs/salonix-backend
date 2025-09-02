from rest_framework import generics, status
from rest_framework.generics import RetrieveUpdateAPIView
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.views import TokenObtainPairView

from .models import UserFeatureFlags, Tenant

from .serializers import (
    EmailTokenObtainPairSerializer,
    UserRegistrationSerializer,
    UserFeatureFlagsSerializer,
    UserFeatureFlagsUpdateSerializer,
    TenantMetaSerializer,
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
    GET /api/tenant/meta?tenant=<slug>

    Endpoint público para obter dados de branding/meta de um tenant.
    Usado para white-label - permite que o frontend obtenha configurações
    visuais (cores, logo, etc.) baseado no tenant.

    Query Parameters:
    - tenant: slug do tenant (obrigatório)

    Headers alternativos:
    - X-Tenant-Slug: slug do tenant
    """

    permission_classes = [AllowAny]
    serializer_class = TenantMetaSerializer

    def get(self, request):
        # Obter tenant slug do query param ou header
        tenant_slug = request.GET.get("tenant") or request.headers.get("X-Tenant-Slug")

        if not tenant_slug:
            return Response(
                {
                    "detail": "Parâmetro 'tenant' ou header 'X-Tenant-Slug' é obrigatório."
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            tenant = Tenant.objects.get(slug=tenant_slug, is_active=True)
        except Tenant.DoesNotExist:
            return Response(
                {"detail": "Tenant não encontrado ou inativo."},
                status=status.HTTP_404_NOT_FOUND,
            )

        serializer = self.serializer_class(tenant)
        return Response(serializer.data)
