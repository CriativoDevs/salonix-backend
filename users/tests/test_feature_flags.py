"""
Testes para o sistema de feature flags baseado em planos.
"""

import pytest
from datetime import timedelta
from rest_framework import status
from rest_framework.test import APIClient
from django.urls import reverse
from django.utils import timezone

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

        # BE-PLANS-01 (#481): Basic absorveu todas as features ex-Pro
        assert tenant.can_use_reports()  # Basic reports
        assert tenant.can_use_basic_reports()
        assert tenant.can_use_standard_reports()
        assert tenant.can_use_advanced_reports()

        assert tenant.can_use_pwa_client()
        assert tenant.can_use_white_label()
        assert tenant.can_use_native_apps()
        # sms_enabled tem default True; com canal habilitado e plano ativo,
        # notificações avançadas ficam disponíveis (feature ex-Pro absorvida)
        assert tenant.can_use_advanced_notifications()

        # PWA Admin sempre habilitado
        assert tenant.pwa_admin_enabled

    def test_pro_plan_features(self):
        """Teste features do plano Pro."""
        tenant = Tenant.objects.create(
            name="Pro Salon",
            slug="pro-salon",
            plan_tier=Tenant.PLAN_PRO,
            # addons_enabled not needed for native apps anymore
            sms_enabled=True,
        )

        # Pro: todas as features básicas + avançadas
        assert tenant.can_use_reports()
        assert tenant.can_use_basic_reports()
        assert tenant.can_use_standard_reports()
        assert tenant.can_use_advanced_reports()

        assert tenant.can_use_pwa_client()
        assert tenant.can_use_white_label()

        # Native Apps (Pro has Admin AND Client)
        assert tenant.can_use_native_admin()
        assert tenant.can_use_native_client()
        assert tenant.can_use_native_apps()

        assert tenant.can_use_advanced_notifications()  # tem SMS

    def test_basic_notifications_with_credits(self):
        tenant = Tenant.objects.create(
            name="Basic Credits Salon",
            slug="basic-credits-salon",
            plan_tier=Tenant.PLAN_BASIC,
            sms_enabled=True,
            comm_extra_allowed=True,
        )
        tenant.comm_credit_eur = 10
        tenant.save()

        assert tenant.can_use_advanced_notifications() is True

    def test_basic_notifications_without_credits(self):
        tenant = Tenant.objects.create(
            name="Basic No Credits",
            slug="basic-no-credits",
            plan_tier=Tenant.PLAN_BASIC,
            whatsapp_enabled=True,
            comm_extra_allowed=True,
        )
        tenant.comm_credit_eur = 0
        tenant.save()

        # BE-PLANS-01 (#481): Basic absorveu notificações avançadas por plano;
        # com canal habilitado, não depende mais de créditos extras.
        assert tenant.can_use_advanced_notifications() is True

    def test_feature_flags_override(self):
        """Teste que feature flags específicas sobrescrevem lógica de plano."""
        tenant = Tenant.objects.create(
            name="Custom Salon",
            slug="custom-salon",
            plan_tier=Tenant.PLAN_BASIC,  # Basic normalmente não tem reports avançados
            reports_enabled=True,  # Mas habilitado explicitamente (se reports_enabled controlasse algo além do básico)
        )

        assert tenant.can_use_reports()  # Deve ser True

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
        assert flags["billing_mode"] == Tenant.BILLING_MODE_STRIPE
        assert flags["addons_enabled"] == ["rn_admin", "rn_client"]
        assert flags["modules"]["reports_enabled"] is True
        assert flags["modules"]["pwa_client_enabled"] is True
        assert flags["modules"]["rn_admin_enabled"] is True
        assert flags["notifications"]["push_web"] is True
        assert flags["notifications"]["sms"] is True
        assert flags["branding"]["white_label_enabled"] is True

    def test_promotional_billing_mode_helpers(self):
        """Valida helper methods do novo billing_mode promocional."""
        tenant = Tenant.objects.create(
            name="Promo Salon",
            slug="promo-salon",
            billing_mode=Tenant.BILLING_MODE_PROMOTIONAL,
        )

        assert tenant.is_promotional_billing() is True
        assert tenant.uses_stripe_billing() is False

    def test_promotional_transition_due_and_apply(self):
        tenant = Tenant.objects.create(
            name="Promo Expired Salon",
            slug="promo-expired-salon",
            plan_tier=Tenant.PLAN_PRO,
            billing_mode=Tenant.BILLING_MODE_PROMOTIONAL,
            promotional_expires_at=timezone.now() - timedelta(days=1),
            promotional_converts_to_plan=Tenant.PLAN_BASIC,
        )

        assert tenant.is_promotional_transition_due() is True
        assert tenant.apply_promotional_transition() is True

        tenant.refresh_from_db()
        assert tenant.billing_mode == Tenant.BILLING_MODE_STRIPE
        assert tenant.plan_tier == Tenant.PLAN_BASIC
        assert tenant.promotional_expires_at is None

    def test_promotional_transition_not_due_yet(self):
        tenant = Tenant.objects.create(
            name="Promo Future Salon",
            slug="promo-future-salon",
            plan_tier=Tenant.PLAN_PRO,
            billing_mode=Tenant.BILLING_MODE_PROMOTIONAL,
            promotional_expires_at=timezone.now() + timedelta(days=3),
            promotional_converts_to_plan=Tenant.PLAN_BASIC,
        )

        assert tenant.is_promotional_transition_due() is False
        assert tenant.apply_promotional_transition() is False

        tenant.refresh_from_db()
        assert tenant.billing_mode == Tenant.BILLING_MODE_PROMOTIONAL
        assert tenant.plan_tier == Tenant.PLAN_PRO


@pytest.mark.django_db
class TestFeatureFlagUtilities:
    """Testes para funções utilitárias de feature flags."""

    def test_check_feature_flag(self, tenant_fixture):
        """Teste função check_feature_flag."""
        tenant_fixture.plan_tier = Tenant.PLAN_PRO
        tenant_fixture.reports_enabled = True
        tenant_fixture.save()

        assert check_feature_flag(tenant_fixture, "reports") is True
        assert check_feature_flag(tenant_fixture, "white_label") is True
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
        tenant_fixture.plan_tier = Tenant.PLAN_PRO
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
        """Teste permission com feature desabilitada.

        BE-PLANS-01 (#481): white_label passou a ser permitido para todos os
        planos ativos; usamos push_mobile com flag desabilitada para validar
        o caminho de negação.
        """
        tenant_fixture.plan_tier = Tenant.PLAN_BASIC
        tenant_fixture.push_mobile_enabled = False
        tenant_fixture.save()

        user_fixture.tenant = tenant_fixture
        user_fixture.save()

        from unittest.mock import Mock

        request = Mock()
        request.user = user_fixture

        permission = RequiresFeatureFlag("push_mobile")
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
        Tenant.objects.create(
            name="Test Salon",
            slug="test-salon",
            plan_tier=Tenant.PLAN_PRO,
            reports_enabled=True,
            push_web_enabled=True,
            app_name="Test Salon App",
        )

        url = reverse("tenant_meta")
        response = self.client.get(url, {"tenant": "test-salon"})

        assert response.status_code == status.HTTP_200_OK
        data = response.json()

        assert data["name"] == "Test Salon"
        assert data["slug"] == "test-salon"
        assert data["plan_tier"] == "pro"
        assert data["app_name"] == "Test Salon App"
        assert data["feature_flags"]["modules"]["reports_enabled"] is True
        assert data["feature_flags"]["notifications"]["push_web"] is True

    def test_tenant_meta_with_header(self):
        """Teste endpoint usando header X-Tenant-Slug."""
        Tenant.objects.create(
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
        Tenant.objects.create(
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

    def test_tenant_meta_patch_auto_invite_success(self):
        """Permite habilitar auto invite quando PWA cliente está disponível."""
        tenant = Tenant.objects.create(
            name="Invite Salon",
            slug="invite-salon",
            plan_tier=Tenant.PLAN_BASIC,
            pwa_client_enabled=True,
        )

        user = CustomUser.objects.create_user(
            username="owner",
            email="owner@invite.com",
            password="testpass123",
            tenant=tenant,
        )

        url = reverse("tenant_meta")
        self.client.force_authenticate(user=user)
        response = self.client.patch(
            url,
            {"auto_invite_enabled": True},
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK
        tenant.refresh_from_db()
        assert tenant.auto_invite_enabled is True
        assert response.json()["auto_invite_enabled"] is True

    def test_tenant_meta_patch_auto_invite_requires_pwa(self):
        """Bloqueia habilitação de auto invite sem PWA cliente."""
        tenant = Tenant.objects.create(
            name="NoPwa",
            slug="nopwa",
            plan_tier=Tenant.PLAN_BASIC,
            pwa_client_enabled=False,
        )

        user = CustomUser.objects.create_user(
            username="basic",
            email="basic@nopwa.com",
            password="testpass123",
            tenant=tenant,
        )

        url = reverse("tenant_meta")
        self.client.force_authenticate(user=user)
        response = self.client.patch(
            url,
            {"auto_invite_enabled": True},
            format="json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "PWA" in response.data["detail"]
        tenant.refresh_from_db()
        assert tenant.auto_invite_enabled is False


@pytest.mark.django_db
class TestPlanUpgradeScenarios:
    """Testes para cenários de upgrade de plano."""

    def test_basic_to_pro_upgrade(self):
        """BE-PLANS-01 (#481): Basic já possui todas as features ex-Pro;
        upgrade para Pro está bloqueado e não é mais necessário."""
        tenant = Tenant.objects.create(
            name="Upgrade Salon",
            slug="upgrade-salon",
            plan_tier=Tenant.PLAN_BASIC,
        )

        # Basic já tem tudo que era do Pro
        assert tenant.can_use_reports()
        assert tenant.can_use_basic_reports()
        assert tenant.can_use_standard_reports()
        assert tenant.can_use_advanced_reports()
        assert tenant.can_use_pwa_client()
        assert tenant.can_use_white_label()

        # E o plano Pro está bloqueado para novas atribuições
        assert Tenant.is_plan_blocked(Tenant.PLAN_PRO) is True
