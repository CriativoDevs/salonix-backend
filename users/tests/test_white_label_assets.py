"""
Testes para funcionalidades de white-label assets (upload de logo, cores).
"""

import pytest
import tempfile
from io import BytesIO
from PIL import Image
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from users.models import CustomUser, Tenant
from users.validators import validate_hex_color, validate_logo_image
from django.core.exceptions import ValidationError


@pytest.mark.django_db
class TestHexColorValidator:
    """Testes para validador de cores hexadecimais."""

    def test_valid_hex_colors(self):
        """Teste cores hexadecimais válidas."""
        valid_colors = [
            "#FF0000",  # Vermelho
            "#00FF00",  # Verde
            "#0000FF",  # Azul
            "#FFFFFF",  # Branco
            "#000000",  # Preto
            "#123ABC",  # Misto maiúsculo
            "#abc123",  # Misto minúsculo
            "#3B82F6",  # Cor padrão do sistema
        ]

        for color in valid_colors:
            # Não deve levantar exceção
            validate_hex_color(color)

    def test_invalid_hex_colors(self):
        """Teste cores hexadecimais inválidas."""
        invalid_colors = [
            "FF0000",  # Sem #
            "#FF00",  # Muito curto
            "#FF00000",  # Muito longo
            "#GGGGGG",  # Caracteres inválidos
            "#ff00zz",  # Caracteres inválidos
            "red",  # Nome de cor
            "#",  # Apenas #
            "123456",  # Sem #
        ]

        for color in invalid_colors:
            with pytest.raises(ValidationError):
                validate_hex_color(color)

    def test_empty_hex_color(self):
        """Teste cor vazia (deve ser permitida)."""
        # None e string vazia devem ser permitidos (campos opcionais)
        validate_hex_color(None)
        validate_hex_color("")


@pytest.mark.django_db
class TestImageValidator:
    """Testes para validador de imagens."""

    def create_test_image(self, format="PNG", size=(100, 100), file_size_kb=None):
        """Cria uma imagem de teste."""
        image = Image.new("RGB", size, color="red")
        image_io = BytesIO()
        image.save(image_io, format=format)
        image_io.seek(0)

        # Se file_size_kb for especificado, ajustar o tamanho do arquivo
        if file_size_kb:
            # Criar um arquivo maior adicionando dados
            content = image_io.getvalue()
            if file_size_kb * 1024 > len(content):
                padding = b"0" * (file_size_kb * 1024 - len(content))
                content += padding
            image_io = BytesIO(content)

        return SimpleUploadedFile(
            f"test.{format.lower()}",
            image_io.getvalue(),
            content_type=f"image/{format.lower()}",
        )

    def test_valid_image_upload(self):
        """Teste upload de imagem válida."""
        # Criar imagem PNG válida
        image_file = self.create_test_image("PNG", (200, 200))

        # Não deve levantar exceção
        validate_logo_image(image_file)

    def test_image_too_large(self):
        """Teste imagem muito grande (tamanho do arquivo)."""
        # Criar imagem de 3MB (acima do limite de 2MB)
        image_file = self.create_test_image("PNG", (100, 100), file_size_kb=3000)

        with pytest.raises(ValidationError, match="muito grande"):
            validate_logo_image(image_file)

    def test_image_too_small(self):
        """Teste imagem muito pequena (dimensões)."""
        # Criar imagem 30x30 (abaixo do mínimo de 50x50)
        image_file = self.create_test_image("PNG", (30, 30))

        with pytest.raises(ValidationError, match="muito pequena"):
            validate_logo_image(image_file)

    def test_image_dimensions_too_large(self):
        """Teste imagem com dimensões muito grandes."""
        # Criar imagem 3000x3000 (acima do máximo de 2000x2000)
        image_file = self.create_test_image("PNG", (3000, 3000))

        with pytest.raises(ValidationError, match="muito grande"):
            validate_logo_image(image_file)

    def test_different_image_formats(self):
        """Teste diferentes formatos de imagem."""
        formats = ["PNG", "JPEG", "GIF", "WEBP"]

        for fmt in formats:
            image_file = self.create_test_image(fmt, (200, 200))
            # Não deve levantar exceção
            validate_logo_image(image_file)


@pytest.mark.django_db
class TestTenantModel:
    """Testes para o modelo Tenant com campos de branding."""

    def test_tenant_logo_url_property(self, tenant_fixture):
        """Teste propriedade get_logo_url."""
        # Sem logo nem logo_url
        assert tenant_fixture.get_logo_url is None

        # Com logo_url apenas
        tenant_fixture.logo_url = "https://example.com/logo.png"
        tenant_fixture.save()
        assert tenant_fixture.get_logo_url == "https://example.com/logo.png"

        # Com logo upload (deve ter prioridade)
        image_file = SimpleUploadedFile(
            "test_logo.png", b"fake_image_content", content_type="image/png"
        )
        tenant_fixture.logo = image_file
        tenant_fixture.save()

        # get_logo_url deve retornar a URL do arquivo upload
        assert "/media/tenant_logos/test_logo" in tenant_fixture.get_logo_url
        assert tenant_fixture.get_logo_url.endswith(".png")

    def test_tenant_hex_color_validation(self, tenant_fixture):
        """Teste validação de cores hex no modelo."""
        # Cor válida
        tenant_fixture.primary_color = "#FF0000"
        tenant_fixture.secondary_color = "#00FF00"
        tenant_fixture.full_clean()  # Deve passar

        # Cor inválida
        tenant_fixture.primary_color = "invalid_color"
        with pytest.raises(ValidationError):
            tenant_fixture.full_clean()


@pytest.mark.django_db
class TestTenantMetaEndpoint:
    """Testes para o endpoint /api/users/tenant/meta/."""

    def setup_method(self):
        self.client = APIClient()

        # Limpar tenants existentes para evitar conflitos
        Tenant.objects.all().delete()

        # Criar tenant de teste
        self.tenant = Tenant.objects.create(
            name="Test Salon",
            slug="test-salon",
            primary_color="#FF0000",
            secondary_color="#00FF00",
        )

        # Criar usuário associado ao tenant
        self.user = CustomUser.objects.create_user(
            username="owner",
            email="owner@test.com",
            password="testpass123",
            tenant=self.tenant,
        )

    def test_get_tenant_meta_success(self):
        """Teste GET bem-sucedido do endpoint meta."""
        url = reverse("users:tenant_meta")
        response = self.client.get(url, {"tenant": "test-salon"})

        assert response.status_code == status.HTTP_200_OK
        assert response.data["name"] == "Test Salon"
        assert response.data["slug"] == "test-salon"
        assert response.data["primary_color"] == "#FF0000"
        assert response.data["secondary_color"] == "#00FF00"
        assert response.data["logo_url"] is None
        assert "feature_flags" in response.data

    def test_get_tenant_meta_with_header(self):
        """Teste GET usando header X-Tenant-Slug."""
        url = reverse("users:tenant_meta")
        response = self.client.get(url, HTTP_X_TENANT_SLUG="test-salon")

        assert response.status_code == status.HTTP_200_OK
        assert response.data["slug"] == "test-salon"

    def test_patch_tenant_meta_unauthorized(self):
        """Teste PATCH sem autenticação."""
        url = reverse("users:tenant_meta")
        response = self.client.patch(url, {"primary_color": "#0000FF"})

        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_patch_tenant_meta_success_colors(self):
        """Teste PATCH bem-sucedido para atualizar cores."""
        self.client.force_authenticate(user=self.user)

        url = reverse("users:tenant_meta")
        data = {"primary_color": "#0000FF", "secondary_color": "#FFFF00"}
        response = self.client.patch(url, data)

        assert response.status_code == status.HTTP_200_OK
        assert response.data["primary_color"] == "#0000FF"
        assert response.data["secondary_color"] == "#FFFF00"

        # Verificar no banco
        self.tenant.refresh_from_db()
        assert self.tenant.primary_color == "#0000FF"
        assert self.tenant.secondary_color == "#FFFF00"

    def test_patch_tenant_meta_invalid_color(self):
        """Teste PATCH com cor inválida."""
        self.client.force_authenticate(user=self.user)

        url = reverse("users:tenant_meta")
        data = {"primary_color": "invalid_color"}
        response = self.client.patch(url, data)

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_patch_tenant_meta_logo_upload(self):
        """Teste PATCH com upload de logo."""
        self.client.force_authenticate(user=self.user)

        # Criar imagem de teste
        image = Image.new("RGB", (200, 200), color="blue")
        image_io = BytesIO()
        image.save(image_io, format="PNG")
        image_io.seek(0)

        logo_file = SimpleUploadedFile(
            "new_logo.png", image_io.getvalue(), content_type="image/png"
        )

        url = reverse("users:tenant_meta")
        data = {"logo": logo_file}
        response = self.client.patch(url, data, format="multipart")

        assert response.status_code == status.HTTP_200_OK
        assert response.data["logo_url"] is not None
        assert "tenant_logos/new_logo" in response.data["logo_url"]

        # Verificar no banco
        self.tenant.refresh_from_db()
        assert self.tenant.logo is not None

    def test_patch_tenant_meta_logo_url(self):
        """Teste PATCH com logo_url externa."""
        self.client.force_authenticate(user=self.user)

        url = reverse("users:tenant_meta")
        data = {"logo_url": "https://example.com/new_logo.png"}
        response = self.client.patch(url, data)

        assert response.status_code == status.HTTP_200_OK
        assert response.data["logo_url"] == "https://example.com/new_logo.png"

        # Verificar no banco
        self.tenant.refresh_from_db()
        assert self.tenant.logo_url == "https://example.com/new_logo.png"

    def test_patch_tenant_meta_logo_and_url_conflict(self):
        """Teste PATCH com logo e logo_url simultaneamente (deve falhar)."""
        self.client.force_authenticate(user=self.user)

        # Criar imagem de teste
        image = Image.new("RGB", (100, 100), color="red")
        image_io = BytesIO()
        image.save(image_io, format="PNG")
        image_io.seek(0)

        logo_file = SimpleUploadedFile(
            "conflict_logo.png", image_io.getvalue(), content_type="image/png"
        )

        url = reverse("users:tenant_meta")
        data = {"logo": logo_file, "logo_url": "https://example.com/conflict.png"}
        response = self.client.patch(url, data, format="multipart")

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "simultaneamente" in str(response.data)

    def test_patch_tenant_meta_updates_own_tenant(self):
        """Teste PATCH atualiza apenas o tenant do próprio usuário."""
        # Criar outro tenant e usuário
        other_tenant = Tenant.objects.create(
            name="Other Salon", slug="other-salon", primary_color="#FFFFFF"
        )
        other_user = CustomUser.objects.create_user(
            username="other_owner",
            email="other@test.com",
            password="testpass123",
            tenant=other_tenant,
        )

        # Autenticar com o outro usuário
        self.client.force_authenticate(user=other_user)

        url = reverse("users:tenant_meta")
        data = {"primary_color": "#000000"}
        response = self.client.patch(url, data)

        # Deve ter sucesso (altera o próprio tenant)
        assert response.status_code == status.HTTP_200_OK
        assert response.data["primary_color"] == "#000000"

        # Verificar que alterou o tenant correto
        other_tenant.refresh_from_db()
        assert other_tenant.primary_color == "#000000"

        # Verificar que o tenant original não foi alterado
        self.tenant.refresh_from_db()
        assert self.tenant.primary_color == "#FF0000"  # Valor original

    def test_patch_tenant_meta_user_without_tenant(self):
        """Teste PATCH com usuário sem tenant."""
        # Usar um mock para simular usuário sem tenant de forma mais robusta
        from unittest.mock import Mock

        # Criar um usuário mock sem tenant
        user_no_tenant = Mock()
        user_no_tenant.is_authenticated = True
        user_no_tenant.tenant = None

        self.client.force_authenticate(user=user_no_tenant)

        url = reverse("users:tenant_meta")
        data = {"primary_color": "#000000"}
        response = self.client.patch(url, data)

        # Com novo sistema de erros, formato padronizado
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "error" in response.data
        assert "não possui tenant" in response.data["error"]["message"]


@pytest.mark.django_db
class TestTenantBrandingIntegration:
    """Testes de integração para funcionalidades de branding."""

    def setup_method(self):
        self.client = APIClient()

        self.tenant = Tenant.objects.create(
            name="Integration Test Salon",
            slug="integration-salon",
        )

        self.user = CustomUser.objects.create_user(
            username="integration_user",
            email="integration@test.com",
            password="testpass123",
            tenant=self.tenant,
        )

    def test_complete_branding_workflow(self):
        """Teste fluxo completo de branding."""
        self.client.force_authenticate(user=self.user)
        url = reverse("users:tenant_meta")

        # 1. Verificar estado inicial
        response = self.client.get(url, {"tenant": "integration-salon"})
        assert response.status_code == status.HTTP_200_OK
        assert response.data["logo_url"] is None

        # 2. Atualizar cores
        color_data = {"primary_color": "#FF5733", "secondary_color": "#33FF57"}
        response = self.client.patch(url, color_data)
        assert response.status_code == status.HTTP_200_OK
        assert response.data["primary_color"] == "#FF5733"

        # 3. Adicionar logo
        image = Image.new("RGB", (150, 150), color="purple")
        image_io = BytesIO()
        image.save(image_io, format="PNG")
        image_io.seek(0)

        logo_file = SimpleUploadedFile(
            "workflow_logo.png", image_io.getvalue(), content_type="image/png"
        )

        logo_data = {"logo": logo_file}
        response = self.client.patch(url, logo_data, format="multipart")
        assert response.status_code == status.HTTP_200_OK
        assert response.data["logo_url"] is not None

        # 4. Verificar estado final via GET público
        response = self.client.get(url, {"tenant": "integration-salon"})
        assert response.status_code == status.HTTP_200_OK
        assert response.data["primary_color"] == "#FF5733"
        assert response.data["secondary_color"] == "#33FF57"
        assert "workflow_logo" in response.data["logo_url"]
