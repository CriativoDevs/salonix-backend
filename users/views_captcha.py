from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import AllowAny
from captcha.models import CaptchaStore
from captcha.helpers import captcha_image_url
from django.conf import settings

class CaptchaGenerateView(APIView):
    permission_classes = [AllowAny]
    throttle_scope = 'anon' # Importante: limitar geração para evitar DDoS

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
