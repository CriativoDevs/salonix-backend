"""
Testes para o endpoint /api/tenant/meta
"""

import pytest
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from users.models import Tenant


@pytest.mark.django_db
class TestTenantMetaView:
    """Testes para o endpoint de branding do tenant"""

    def setup_method(self):
        self.client = APIClient()

        # Criar tenants para teste
        self.active_tenant = Tenant.objects.create(
            name="Salão Exemplo",
            slug="salao-exemplo",
            logo_url="https://example.com/logo.png",
            primary_color="#FF6B6B",
            secondary_color="#4ECDC4",
            timezone="America/Sao_Paulo",
            currency="BRL",
            is_active=True,
        )

        self.inactive_tenant = Tenant.objects.create(
            name="Salão Inativo",
            slug="salao-inativo",
            primary_color="#000000",
            secondary_color="#FFFFFF",
            is_active=False,
        )

    def test_get_tenant_meta_with_query_param(self):
        """Teste obter meta do tenant via query parameter"""
        url = reverse("tenant_meta")
        response = self.client.get(url, {"tenant": "salao-exemplo"})

        assert response.status_code == status.HTTP_200_OK

        data = response.json()
        assert data["name"] == "Salão Exemplo"
        assert data["slug"] == "salao-exemplo"
        assert data["logo_url"] == "https://example.com/logo.png"
        assert data["primary_color"] == "#FF6B6B"
        assert data["secondary_color"] == "#4ECDC4"
        assert data["timezone"] == "America/Sao_Paulo"
        assert data["currency"] == "BRL"

    def test_get_tenant_meta_with_header(self):
        """Teste obter meta do tenant via header X-Tenant-Slug"""
        url = reverse("tenant_meta")
        response = self.client.get(url, HTTP_X_TENANT_SLUG="salao-exemplo")

        assert response.status_code == status.HTTP_200_OK

        data = response.json()
        assert data["name"] == "Salão Exemplo"
        assert data["slug"] == "salao-exemplo"

    def test_query_param_takes_priority_over_header(self):
        """Teste que query param tem prioridade sobre header"""
        url = reverse("tenant_meta")
        response = self.client.get(
            url, {"tenant": "salao-exemplo"}, HTTP_X_TENANT_SLUG="salao-inativo"
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["slug"] == "salao-exemplo"  # Query param foi usado

    def test_missing_tenant_parameter(self):
        """Teste erro quando tenant não é fornecido"""
        url = reverse("tenant_meta")
        response = self.client.get(url)

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "obrigatório" in response.json()["detail"]

    def test_nonexistent_tenant(self):
        """Teste erro quando tenant não existe"""
        url = reverse("tenant_meta")
        response = self.client.get(url, {"tenant": "tenant-inexistente"})

        assert response.status_code == status.HTTP_404_NOT_FOUND
        assert "não encontrado" in response.json()["detail"]

    def test_inactive_tenant(self):
        """Teste erro quando tenant está inativo"""
        url = reverse("tenant_meta")
        response = self.client.get(url, {"tenant": "salao-inativo"})

        assert response.status_code == status.HTTP_404_NOT_FOUND
        assert "não encontrado" in response.json()["detail"]

    def test_endpoint_is_public(self):
        """Teste que o endpoint é público (não requer autenticação)"""
        url = reverse("tenant_meta")
        response = self.client.get(url, {"tenant": "salao-exemplo"})

        # Não deve retornar 401 (unauthorized)
        assert response.status_code == status.HTTP_200_OK

    def test_tenant_meta_fields_are_read_only(self):
        """Teste que o endpoint é apenas GET (read-only)"""
        url = reverse("tenant_meta")

        # Testar POST
        response = self.client.post(url, {"tenant": "salao-exemplo"})
        assert response.status_code == status.HTTP_405_METHOD_NOT_ALLOWED

        # Testar PUT
        response = self.client.put(url, {"tenant": "salao-exemplo"})
        assert response.status_code == status.HTTP_405_METHOD_NOT_ALLOWED

        # Testar PATCH
        response = self.client.patch(url, {"tenant": "salao-exemplo"})
        assert response.status_code == status.HTTP_405_METHOD_NOT_ALLOWED

        # Testar DELETE
        response = self.client.delete(url, {"tenant": "salao-exemplo"})
        assert response.status_code == status.HTTP_405_METHOD_NOT_ALLOWED

    def test_tenant_with_minimal_data(self):
        """Teste tenant com dados mínimos (campos opcionais vazios)"""
        minimal_tenant = Tenant.objects.create(
            name="Salão Mínimo",
            slug="salao-minimo",
            # logo_url não definido (None)
            # cores usam defaults
            is_active=True,
        )

        url = reverse("tenant_meta")
        response = self.client.get(url, {"tenant": "salao-minimo"})

        assert response.status_code == status.HTTP_200_OK
        data = response.json()

        assert data["name"] == "Salão Mínimo"
        assert data["logo_url"] is None
        assert data["primary_color"] == "#3B82F6"  # Default
        assert data["secondary_color"] == "#1F2937"  # Default
        assert data["timezone"] == "Europe/Lisbon"  # Default
        assert data["currency"] == "EUR"  # Default
