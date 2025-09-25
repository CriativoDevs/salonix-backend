"""
Testes para o sistema de feature flags baseado em planos.
"""

import pytest
from rest_framework import status
from rest_framework.test import APIClient
from django.urls import reverse

from users.models import Tenant, CustomUser
from users.feature_flags import (
    check_feature_flag,
    get_tenant_feature_summary,
    RequiresFeatureFlag,
)


@pytest.mark.django_db
class TestTenantFeatureFlags:
    """Testes para feature flags no modelo Tenant."""

    def test_basic_plan_features(self):
        """Teste features do plano Basic."""
        tenant = Tenant.objects.create(
            name="Basic Salon",
            slug="basic-salon",
            plan_tier=Tenant.PLAN_BASIC,
        )

        # Basic: apenas PWA Admin habilitado por padrão
        assert not tenant.can_use_reports()
        assert not tenant.can_use_pwa_client()
        assert not tenant.can_use_white_label()
        assert not tenant.can_use_native_apps()
        assert not tenant.can_use_advanced_notifications()

        # PWA Admin sempre habilitado
        assert tenant.pwa_admin_enabled

    def test_standard_plan_features(self):
        """Teste features do plano Standard."""
        tenant = Tenant.objects.create(
            name="Standard Salon",
            slug="standard-salon",
            plan_tier=Tenant.PLAN_STANDARD,
        )

        # Standard: reports + PWA client
        assert tenant.can_use_reports()
        assert tenant.can_use_pwa_client()
        assert not tenant.can_use_white_label()
        assert not tenant.can_use_native_apps()
        assert not tenant.can_use_advanced_notifications()

    def test_pro_plan_features(self):
        """Teste features do plano Pro."""
        tenant = Tenant.objects.create(
            name="Pro Salon",
            slug="pro-salon",
            plan_tier=Tenant.PLAN_PRO,
            addons_enabled=["rn_admin"],
            sms_enabled=True,
        )

        # Pro: todas as features básicas
        assert tenant.can_use_reports()
        assert tenant.can_use_pwa_client()
        assert tenant.can_use_white_label()
        assert tenant.can_use_native_apps()  # tem addon rn_admin
        assert tenant.can_use_advanced_notifications()  # tem SMS

    def test_enterprise_plan_features(self):
        """Teste features do plano Enterprise."""
        tenant = Tenant.objects.create(
            name="Enterprise Salon",
            slug="enterprise-salon",
            plan_tier=Tenant.PLAN_ENTERPRISE,
            addons_enabled=["rn_admin", "rn_client"],
            sms_enabled=True,
            whatsapp_enabled=True,
        )

        assert tenant.can_use_reports()
        assert tenant.can_use_pwa_client()
        assert tenant.can_use_white_label()
        assert tenant.can_use_native_apps()
        assert tenant.can_use_advanced_notifications()

    def test_feature_flags_override(self):
        """Teste que feature flags específicas sobrescrevem lógica de plano."""
        tenant = Tenant.objects.create(
            name="Custom Salon",
            slug="custom-salon",
            plan_tier=Tenant.PLAN_BASIC,  # Basic normalmente não tem reports
            reports_enabled=True,  # Mas habilitado explicitamente
        )

        assert tenant.can_use_reports()  # Deve ser True por causa do override

    def test_notification_channels(self):
        """Teste canais de notificação habilitados."""
        tenant = Tenant.objects.create(
            name="Notification Salon",
            slug="notification-salon",
            plan_tier=Tenant.PLAN_PRO,
            push_web_enabled=True,
            push_mobile_enabled=True,
            sms_enabled=True,
            whatsapp_enabled=True,
        )

        channels = tenant.get_enabled_notification_channels()
        expected = ["in_app", "push_web", "push_mobile", "sms", "whatsapp"]
        assert set(channels) == set(expected)

    def test_feature_flags_dict(self):
        """Teste serialização completa das feature flags."""
        tenant = Tenant.objects.create(
            name="Full Feature Salon",
            slug="full-salon",
            plan_tier=Tenant.PLAN_PRO,
            addons_enabled=["rn_admin", "rn_client"],
            reports_enabled=True,
            pwa_client_enabled=True,
            rn_admin_enabled=True,  # Precisa estar habilitado explicitamente
            rn_client_enabled=True,  # Precisa estar habilitado explicitamente
            push_web_enabled=True,
            sms_enabled=True,
        )

        flags = tenant.get_feature_flags_dict()

        assert flags["plan_tier"] == "pro"
        assert flags["addons_enabled"] == ["rn_admin", "rn_client"]
        assert flags["modules"]["reports_enabled"] is True
        assert flags["modules"]["pwa_client_enabled"] is True
        assert flags["modules"]["rn_admin_enabled"] is True
        assert flags["notifications"]["push_web"] is True
        assert flags["notifications"]["sms"] is True
        assert flags["branding"]["white_label_enabled"] is True


@pytest.mark.django_db
class TestFeatureFlagUtilities:
    """Testes para funções utilitárias de feature flags."""

    def test_check_feature_flag(self, tenant_fixture):
        """Teste função check_feature_flag."""
        tenant_fixture.plan_tier = Tenant.PLAN_STANDARD
        tenant_fixture.reports_enabled = True
        tenant_fixture.save()

        assert check_feature_flag(tenant_fixture, "reports") is True
        assert check_feature_flag(tenant_fixture, "white_label") is False
        assert check_feature_flag(None, "reports") is False

    def test_get_tenant_feature_summary(self, tenant_fixture):
        """Teste função get_tenant_feature_summary."""
        tenant_fixture.plan_tier = Tenant.PLAN_PRO
        tenant_fixture.push_web_enabled = True
        tenant_fixture.save()

        summary = get_tenant_feature_summary(tenant_fixture)

        assert summary["plan_tier"] == "pro"
        assert summary["available_features"]["white_label"] is True
        assert summary["available_features"]["push_web"] is True
        assert "in_app" in summary["enabled_notification_channels"]


@pytest.mark.django_db
class TestRequiresFeatureFlagPermission:
    """Testes para permission RequiresFeatureFlag."""

    def setup_method(self):
        """Setup para cada teste."""
        self.client = APIClient()

    def test_permission_with_valid_feature(self, tenant_fixture, user_fixture):
        """Teste permission com feature habilitada."""
        # Configurar tenant com reports habilitados
        tenant_fixture.plan_tier = Tenant.PLAN_STANDARD
        tenant_fixture.reports_enabled = True
        tenant_fixture.save()

        user_fixture.tenant = tenant_fixture
        user_fixture.save()

        # Simular request
        from unittest.mock import Mock

        request = Mock()
        request.user = user_fixture

        permission = RequiresFeatureFlag("reports")
        assert permission.has_permission(request, None) is True

    def test_permission_without_feature(self, tenant_fixture, user_fixture):
        """Teste permission com feature desabilitada."""
        # Tenant básico sem reports
        tenant_fixture.plan_tier = Tenant.PLAN_BASIC
        tenant_fixture.reports_enabled = False
        tenant_fixture.save()

        user_fixture.tenant = tenant_fixture
        user_fixture.save()

        from unittest.mock import Mock

        request = Mock()
        request.user = user_fixture

        permission = RequiresFeatureFlag("reports")
        assert permission.has_permission(request, None) is False

    def test_permission_without_tenant(self):
        """Teste permission sem tenant associado."""
        from users.models import CustomUser
        from unittest.mock import Mock

        # Criar usuário sem tenant
        user = CustomUser.objects.create_user(
            username="notenant",
            email="notenant@test.com",
            password="testpass123",
            tenant=None,
        )
        # Marcar explicitamente que o tenant deve ser None
        user._tenant_explicitly_none = True
        user.tenant = None
        user.save()

        request = Mock()
        request.user = user

        permission = RequiresFeatureFlag("reports")
        assert permission.has_permission(request, None) is False


@pytest.mark.django_db
class TestTenantMetaEndpoint:
    """Testes para o endpoint /api/users/tenant/meta/."""

    def setup_method(self):
        """Setup para cada teste."""
        self.client = APIClient()

    def test_tenant_meta_success(self):
        """Teste endpoint com tenant válido."""
        tenant = Tenant.objects.create(
            name="Test Salon",
            slug="test-salon",
            plan_tier=Tenant.PLAN_STANDARD,
            reports_enabled=True,
            push_web_enabled=True,
            primary_color="#FF0000",
        )

        url = reverse("tenant_meta")
        response = self.client.get(url, {"tenant": "test-salon"})

        assert response.status_code == status.HTTP_200_OK
        data = response.json()

        assert data["name"] == "Test Salon"
        assert data["slug"] == "test-salon"
        assert data["plan_tier"] == "standard"
        assert data["primary_color"] == "#FF0000"
        assert data["feature_flags"]["modules"]["reports_enabled"] is True
        assert data["feature_flags"]["notifications"]["push_web"] is True

    def test_tenant_meta_with_header(self):
        """Teste endpoint usando header X-Tenant-Slug."""
        tenant = Tenant.objects.create(
            name="Header Salon",
            slug="header-salon",
            plan_tier=Tenant.PLAN_PRO,
        )

        url = reverse("tenant_meta")
        response = self.client.get(url, HTTP_X_TENANT_SLUG="header-salon")

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["slug"] == "header-salon"
        assert data["feature_flags"]["branding"]["white_label_enabled"] is True

    def test_tenant_meta_not_found(self):
        """Teste endpoint com tenant inexistente."""
        url = reverse("tenant_meta")
        response = self.client.get(url, {"tenant": "non-existent"})

        # Com novo sistema de erros, retorna 400 com formato padronizado
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "error" in response.data
        assert "não encontrado" in response.data["error"]["message"]

    def test_tenant_meta_missing_param(self):
        """Teste endpoint sem parâmetro tenant."""
        url = reverse("tenant_meta")
        response = self.client.get(url)

        # Com novo sistema de erros, formato padronizado
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "error" in response.data
        assert "obrigatório" in response.data["error"]["message"]

    def test_tenant_meta_inactive_tenant(self):
        """Teste endpoint com tenant inativo."""
        tenant = Tenant.objects.create(
            name="Inactive Salon",
            slug="inactive-salon",
            is_active=False,
        )

        url = reverse("tenant_meta")
        response = self.client.get(url, {"tenant": "inactive-salon"})

        # Com novo sistema de erros, retorna 400 com formato padronizado
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "error" in response.data
        assert "inativo" in response.data["error"]["message"]


@pytest.mark.django_db
class TestPlanUpgradeScenarios:
    """Testes para cenários de upgrade de plano."""

    def test_basic_to_standard_upgrade(self):
        """Teste upgrade de Basic para Standard."""
        tenant = Tenant.objects.create(
            name="Upgrade Salon",
            slug="upgrade-salon",
            plan_tier=Tenant.PLAN_BASIC,
        )

        # Antes do upgrade
        assert not tenant.can_use_reports()
        assert not tenant.can_use_pwa_client()

        # Simular upgrade
        tenant.plan_tier = Tenant.PLAN_STANDARD
        tenant.save()

        # Depois do upgrade
        assert tenant.can_use_reports()
        assert tenant.can_use_pwa_client()
        assert not tenant.can_use_white_label()  # Ainda não é Pro

    def test_standard_to_pro_upgrade(self):
        """Teste upgrade de Standard para Pro."""
        tenant = Tenant.objects.create(
            name="Pro Upgrade Salon",
            slug="pro-upgrade-salon",
            plan_tier=Tenant.PLAN_STANDARD,
        )

        # Antes do upgrade
        assert not tenant.can_use_white_label()
        assert not tenant.can_use_native_apps()

        # Simular upgrade para Pro com addons
        tenant.plan_tier = Tenant.PLAN_PRO
        tenant.addons_enabled = ["rn_admin"]
        tenant.sms_enabled = True
        tenant.save()

        # Depois do upgrade
        assert tenant.can_use_white_label()
        assert tenant.can_use_native_apps()
        assert tenant.can_use_advanced_notifications()
