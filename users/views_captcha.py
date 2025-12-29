from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework import serializers
from captcha.models import CaptchaStore
from captcha.helpers import captcha_image_url
from django.conf import settings
from drf_spectacular.utils import extend_schema, OpenApiResponse

class CaptchaResponseSerializer(serializers.Serializer):
    key = serializers.CharField(help_text="Chave única para validação posterior (enviar como captcha_key)")
    image_url = serializers.URLField(help_text="URL completa da imagem do desafio")

class CaptchaGenerateView(APIView):
    permission_classes = [AllowAny]
    throttle_scope = 'anon' # Importante: limitar geração para evitar DDoS

    @extend_schema(
        summary="Gera novo desafio Captcha",
        description="Retorna uma chave e uma URL de imagem para desafio captcha simples. A chave deve ser enviada junto com a resposta do usuário nos endpoints protegidos.",
        responses={
            200: OpenApiResponse(response=CaptchaResponseSerializer, description="Desafio gerado com sucesso"),
            429: OpenApiResponse(description="Muitas solicitações (Rate Limit)")
        }
    )
    def get(self, request):
        """
        Gera um novo desafio de captcha.
        Retorna:
        - key: chave única para validação posterior
        - image_url: URL da imagem do desafio
        """
        # Gera hash e salva no banco
        hash_key = CaptchaStore.generate_key()
        image_url = captcha_image_url(hash_key)
        
        # Constrói URL completa se necessário
        full_image_url = request.build_absolute_uri(image_url)

        return Response({
            "key": hash_key,
            "image_url": full_image_url
        }, status=status.HTTP_200_OK)
