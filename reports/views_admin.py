# reports/views_admin.py
from typing import List

from rest_framework.views import APIView
from rest_framework.permissions import IsAdminUser, IsAuthenticated
from rest_framework.response import Response
from rest_framework import status

from drf_spectacular.utils import extend_schema, OpenApiExample
from drf_spectacular.types import OpenApiTypes

from reports.utils.cache import invalidate_cache


class CacheInvalidateView(APIView):
    """
    Endpoint administrativo para invalidar cache por prefixo.
    POST body:
      { "prefixes": ["reports:overview:", "reports:top_services:"] }

    Retorna a contagem total de chaves removidas.
    """

    permission_classes = [IsAuthenticated, IsAdminUser]

    @extend_schema(
        tags=["Reports • Admin"],
        summary="Invalidar cache por prefixo (admin-only)",
        request={
            "type": "object",
            "properties": {
                "prefixes": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Lista de prefixos a invalidar (ex.: reports:overview:).",
                }
            },
            "required": ["prefixes"],
        },
        responses={
            200: {
                "type": "object",
                "properties": {
                    "removed": {"type": "integer", "example": 12},
                    "details": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "prefix": {"type": "string"},
                                "removed": {"type": "integer"},
                            },
                        },
                    },
                },
            },
            400: OpenApiTypes.OBJECT,
            403: OpenApiTypes.OBJECT,
        },
        examples=[
            OpenApiExample(
                "Exemplo requisição",
                value={"prefixes": ["reports:overview:", "reports:revenue:"]},
                request_only=True,
            )
        ],
    )
    def post(self, request):
        prefixes: List[str] = request.data.get("prefixes") or []
        if not isinstance(prefixes, list) or not all(
            isinstance(p, str) for p in prefixes
        ):
            return Response(
                {"detail": "Campo 'prefixes' deve ser uma lista de strings."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if not prefixes:
            return Response(
                {"detail": "Informe ao menos um prefixo em 'prefixes'."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        total = 0
        details = []
        for p in prefixes:
            removed = invalidate_cache(p)
            total += removed
            details.append({"prefix": p, "removed": removed})

        return Response({"removed": total, "details": details}, status=200)
