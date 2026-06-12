import pytest
from decimal import Decimal
from django.contrib.auth import get_user_model
from users.models import Tenant, UserFeatureFlags

User = get_user_model()


@pytest.mark.django_db
class TestPlanFeatures:
    """
    Testes para validar a atribuição de features e permissões
    baseadas nos planos (Basic, Pro) e no status Founder.
    """

    def test_basic_plan_features(self):
        """Valida features do plano Basic."""
        tenant = Tenant.objects.create(
            name="Basic Salon",
            slug="basic-salon",
            plan_tier=Tenant.PLAN_BASIC,
        )

        # BE-PLANS-01 (#481): Basic absorveu todas as features ex-Pro
        assert tenant.can_use_basic_reports() is True
        assert tenant.can_use_standard_reports() is True
        assert tenant.can_use_advanced_reports() is True
        assert tenant.can_use_pwa_client() is True
        assert tenant.can_use_native_apps() is True
        assert tenant.can_use_white_label() is True
        # Domínio custom continua dependendo da flag explícita
        assert tenant.can_use_custom_domain() is False

    def test_pro_plan_features(self):
        """Valida features do plano Pro."""
        tenant = Tenant.objects.create(
            name="Pro Salon",
            slug="pro-salon",
            plan_tier=Tenant.PLAN_PRO,
            custom_domain_enabled=True,
            rn_admin_enabled=True,
        )

        # Features esperadas
        assert tenant.can_use_basic_reports() is True
        assert tenant.can_use_standard_reports() is True
        assert tenant.can_use_advanced_reports() is True
        assert tenant.can_use_pwa_client() is True
        assert tenant.can_use_native_apps() is True  # Via rn_admin_enabled ou plan tier
        assert tenant.can_use_white_label() is True
        assert tenant.can_use_custom_domain() is True

    def test_founder_plan_inheritance(self):
        """
        Valida que um tenant Founder herda as features do plano Basic.
        O status Founder é ortogonal ao plan_tier (que deve ser Basic).
        """
        tenant = Tenant.objects.create(
            name="Founder Salon",
            slug="founder-salon",
            plan_tier=Tenant.PLAN_BASIC,  # Webhook força Basic
            is_founder=True,
        )

        # BE-PLANS-01 (#481): Founder/Basic têm todas as features ex-Pro
        assert tenant.can_use_basic_reports() is True
        assert tenant.can_use_standard_reports() is True
        assert tenant.can_use_advanced_reports() is True
        assert tenant.can_use_pwa_client() is True
        assert tenant.can_use_white_label() is True
        # Domínio custom continua dependendo da flag explícita
        assert tenant.can_use_custom_domain() is False

    def test_founder_plan_credits(self):
        """
        Valida que o Founder recebe os créditos iniciais corretos (2.00 EUR).
        """
        tenant = Tenant.objects.create(
            name="Founder Credits",
            slug="founder-credits",
            plan_tier=Tenant.PLAN_BASIC,
            is_founder=True,
        )

        # Recarrega do banco para pegar atualização do signal
        tenant.refresh_from_db()

        assert tenant.comm_credit_eur == Decimal("2.00")

    def test_legacy_founder_tier_behavior(self):
        """
        Verifica o comportamento se um tenant tiver plan_tier='founder' (legado/erro).
        Isso ajuda a identificar se precisamos migrar dados antigos.
        """
        tenant = Tenant.objects.create(
            name="Legacy Founder",
            slug="legacy-founder",
            plan_tier=Tenant.PLAN_FOUNDER,
            is_founder=True,
        )

        # Se o tier for explicitamente 'founder', ele tem acesso a reports básicos?
        # Pelo código atual: Sim, can_use_basic_reports inclui PLAN_FOUNDER.
        assert tenant.can_use_basic_reports() is True

        # E PWA Client?
        assert tenant.pwa_client_enabled is True
        assert tenant.can_use_pwa_client() is True

        # BE-PLANS-01 (#481): PLAN_FOUNDER entrou na lista de planos permitidos
        # de can_use_pwa_client; mesmo sem a flag explícita, mantém acesso.
        tenant.pwa_client_enabled = False
        tenant.save()
        assert tenant.can_use_pwa_client() is True

        # Conclusão: É seguro manter PLAN_FOUNDER como fallback,
        # mas o ideal é que todos sejam plan_tier='basic'.
