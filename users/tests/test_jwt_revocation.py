import pytest
from rest_framework.test import APIClient
from django.urls import reverse
from rest_framework_simplejwt.tokens import RefreshToken


@pytest.mark.django_db
class TestJWTRevocation:
    def test_token_revocation_on_version_increment(self, user_fixture):
        """
        Testa se o incremento de jwt_version invalida tokens antigos.
        """
        client = APIClient()
        user = user_fixture

        # Garantir versão inicial 1
        user.jwt_version = 1
        user.save()

        # 1. Gerar token manualmente (simulando login com versão 1)
        refresh = RefreshToken.for_user(user)
        refresh["jwt_version"] = 1
        access_token = str(refresh.access_token)

        # 2. Tentar usar token (deve funcionar)
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {access_token}")
        url = reverse("me_profile")
        response = client.get(url)
        assert response.status_code == 200, "Token válido deveria funcionar"

        # 3. Incrementar versão do usuário (simulando downgrade de plano)
        user.jwt_version = 2
        user.save()

        # 4. Tentar usar o mesmo token (deve falhar)
        response = client.get(url)
        assert (
            response.status_code == 401
        ), "Token com versão antiga deveria ser rejeitado"
        # O código de erro pode variar dependendo de como o DRF serializa a exceção
        # Mas verificamos se foi rejeitado

    def test_token_without_version_behavior(self, user_fixture):
        """
        Testa comportamento de tokens legados (sem campo versão).
        Se usuário user.jwt_version > 1, token legado deve ser rejeitado.
        """
        client = APIClient()
        user = user_fixture
        user.jwt_version = 2  # Usuário atualizado
        user.save()

        # Token antigo (sem jwt_version)
        refresh = RefreshToken.for_user(user)
        # NÃO adicionamos jwt_version
        access_token = str(refresh.access_token)

        client.credentials(HTTP_AUTHORIZATION=f"Bearer {access_token}")
        url = reverse("me_profile")
        response = client.get(url)

        assert response.status_code == 401
