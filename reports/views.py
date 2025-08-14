from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework import status
from django.utils import timezone

from users.models import UserFeatureFlags


class ReportsSummaryView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        # garante que o registro exista (evita AttributeError em usuários antigos)
        flags, _ = UserFeatureFlags.objects.get_or_create(user=request.user)

        if not flags.reports_enabled:
            return Response(
                {"detail": "Módulo de relatórios desativado."},
                status=status.HTTP_403_FORBIDDEN,
            )

        # payload mockado por enquanto (podemos trocar depois por dados reais)
        data = {
            "range": "last_30_days",
            "generated_at": timezone.now(),
            "appointments_total": 42,
            "revenue_estimated": 1234.56,
        }
        return Response(data, status=status.HTTP_200_OK)
