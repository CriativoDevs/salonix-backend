"""
Testes para validação de acesso aos apps mobile baseado no plano do tenant.

BE-MOBILE-SEC-01: Implementa validação de header X-App-Type no endpoint de login
para prevenir que tenants com planos insuficientes obtenham tokens JWT para apps
mobile aos quais não têm direito.

Cenários testados:
- Admin App requer plano Standard+
- Client App requer plano Pro
- Web login (sem header) funciona independente do plano
"""

from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from users.models import Tenant

User = get_user_model()


@pytest.fixture
def api_client():
    """Cliente API para requests HTTP"""
    return APIClient()


@pytest.fixture
def tenant_basic(db):
    """Cria tenant com plano Basic (€29/mês) - sem acesso mobile"""
    from users.models import Tenant

    tenant = Tenant.objects.create(
        name="Basic Tenant",
        slug="basic-tenant",
        plan_tier="basic",
    )
    user = User.objects.create_user(
        username="basic_owner",
        email="owner@basictenant.com",
        password="Test123!@#",
        tenant=tenant,
    )
    return tenant


@pytest.fixture
def tenant_pro(db):
    """Cria tenant com plano Pro (€99/mês) - Admin + Client Apps habilitados"""
    from users.models import Tenant

    tenant = Tenant.objects.create(
        name="Pro Tenant",
        slug="pro-tenant",
        plan_tier="pro",
    )
    user = User.objects.create_user(
        username="pro_owner",
        email="owner@protenant.com",
        password="Test123!@#",
        tenant=tenant,
    )
    return tenant


@pytest.fixture
def tenant_with_admin_flag(db):
    """Cria tenant Basic mas com rn_admin_enabled=True (acesso manual)"""
    from users.models import Tenant

    tenant = Tenant.objects.create(
        name="Flagged Tenant",
        slug="flagged-tenant",
        plan_tier="basic",
        rn_admin_enabled=True,  # Access granted manually
    )
    user = User.objects.create_user(
        username="flagged_owner",
        email="owner@flaggedtenant.com",
        password="Test123!@#",
        tenant=tenant,
    )
    return tenant


@pytest.mark.django_db
class TestMobileAppAccessControl:
    """Testes de controle de acesso aos apps mobile baseado em plano"""

    @pytest.fixture(autouse=True)
    def setup(self, api_client):
        from django.core.cache import cache

        cache.clear()  # Limpar throttle cache entre testes
        self.client = api_client
        self.token_url = reverse("token_obtain_pair")

    # ========================================================================
    # ADMIN APP ACCESS TESTS
    # ========================================================================

    def test_basic_tenant_can_access_admin_app(self, tenant_basic):
        """BE-PLANS-01 (#481): Basic absorveu apps nativos; login admin liberado."""
        response = self.client.post(
            self.token_url,
            data={
                "email": "owner@basictenant.com",
                "password": "Test123!@#",
            },
            HTTP_X_APP_TYPE="admin",
        )

        assert response.status_code == status.HTTP_200_OK
        assert "access" in response.data

    def test_tenant_without_entitlement_cannot_access_admin_app(self, tenant_basic):
        """Sem entitlement (mockado), login no Admin App → HTTP 403 com upgrade."""
        from users.models import Tenant

        with patch.object(Tenant, "can_use_native_admin", return_value=False):
            response = self.client.post(
                self.token_url,
                data={
                    "email": "owner@basictenant.com",
                    "password": "Test123!@#",
                },
                HTTP_X_APP_TYPE="admin",
            )

        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert "detail" in response.data
        assert "Pro" in response.data["detail"]  # Mention required plan
        assert response.data["plan_required"] == "pro"
        assert response.data["current_plan"] == "basic"
        assert "upgrade_url" in response.data

    def test_pro_tenant_can_access_admin_app(self, tenant_pro):
        """
        Pro tenant (€99) loga no Admin App → HTTP 200 + tokens

        Expectativa: Login bem-sucedido (Pro inclui Admin features)
        """
        response = self.client.post(
            self.token_url,
            data={
                "email": "owner@protenant.com",
                "password": "Test123!@#",
            },
            HTTP_X_APP_TYPE="admin",
        )

        assert response.status_code == status.HTTP_200_OK
        assert "access" in response.data
        assert "refresh" in response.data

    def test_tenant_with_rn_admin_flag_can_access_admin_app(
        self, tenant_with_admin_flag
    ):
        """
        Basic tenant com rn_admin_enabled=True loga no Admin App → HTTP 200

        Expectativa: Feature flag sobrescreve validação de plano
        """
        response = self.client.post(
            self.token_url,
            data={
                "email": "owner@flaggedtenant.com",
                "password": "Test123!@#",
            },
            HTTP_X_APP_TYPE="admin",
        )

        assert response.status_code == status.HTTP_200_OK
        assert "access" in response.data

    # ========================================================================
    # CLIENT APP ACCESS TESTS
    # ========================================================================

    def test_basic_tenant_can_access_client_app(self, tenant_basic):
        """BE-PLANS-01 (#481): Basic absorveu apps nativos; login client liberado."""
        response = self.client.post(
            self.token_url,
            data={
                "email": "owner@basictenant.com",
                "password": "Test123!@#",
            },
            HTTP_X_APP_TYPE="client",
        )

        assert response.status_code == status.HTTP_200_OK
        assert "access" in response.data

    def test_tenant_without_entitlement_cannot_access_client_app(self, tenant_basic):
        """Sem entitlement (mockado), login no Client App → HTTP 403 com upgrade."""
        from users.models import Tenant

        with patch.object(Tenant, "can_use_native_client", return_value=False):
            response = self.client.post(
                self.token_url,
                data={
                    "email": "owner@basictenant.com",
                    "password": "Test123!@#",
                },
                HTTP_X_APP_TYPE="client",
            )

        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert "Pro" in response.data["detail"]  # Mention Pro plan
        assert response.data["plan_required"] == "pro"
        assert response.data["current_plan"] == "basic"

    def test_pro_tenant_can_access_client_app(self, tenant_pro):
        """
        Pro tenant (€99) loga no Client App → HTTP 200 + tokens

        Expectativa: Login bem-sucedido
        """
        response = self.client.post(
            self.token_url,
            data={
                "email": "owner@protenant.com",
                "password": "Test123!@#",
            },
            HTTP_X_APP_TYPE="client",
        )

        assert response.status_code == status.HTTP_200_OK
        assert "access" in response.data
        assert "refresh" in response.data

    @pytest.mark.parametrize(
        ("app_type", "flag_field"),
        (("admin", "rn_admin_enabled"), ("client", "rn_client_enabled")),
    )
    def test_promotional_tenant_can_login_mobile_without_subscription(
        self, app_type, flag_field
    ):
        tenant = Tenant.objects.create(
            name=f"Promo {app_type.title()} Tenant",
            slug=f"promo-{app_type}-tenant",
            plan_tier=Tenant.PLAN_BASIC,
            billing_mode=Tenant.BILLING_MODE_PROMOTIONAL,
            **{flag_field: True},
        )
        User.objects.create_user(
            username=f"promo_{app_type}_owner",
            email=f"promo-{app_type}@tenant.com",
            password="Test123!@#",
            tenant=tenant,
        )

        response = self.client.post(
            self.token_url,
            data={
                "email": f"promo-{app_type}@tenant.com",
                "password": "Test123!@#",
            },
            HTTP_X_APP_TYPE=app_type,
        )

        assert response.status_code == status.HTTP_200_OK
        assert (
            response.data["tenant"]["plan"]["billing_mode"]
            == Tenant.BILLING_MODE_PROMOTIONAL
        )

    # ========================================================================
    # WEB LOGIN (NO HEADER) TESTS
    # ========================================================================

    def test_web_login_works_for_basic_tenant(self, tenant_basic):
        """
        Basic tenant faz login web (sem X-App-Type) → HTTP 200

        Expectativa: Web login sempre funciona independente do plano
        """
        response = self.client.post(
            self.token_url,
            data={
                "email": "owner@basictenant.com",
                "password": "Test123!@#",
            },
            # No X-App-Type header → defaults to 'web'
        )

        assert response.status_code == status.HTTP_200_OK
        assert "access" in response.data

    def test_web_login_works_for_pro_tenant(self, tenant_pro):
        """
        Pro tenant faz login web → HTTP 200

        Expectativa: Web login sempre funciona
        """
        response = self.client.post(
            self.token_url,
            data={
                "email": "owner@protenant.com",
                "password": "Test123!@#",
            },
        )

        assert response.status_code == status.HTTP_200_OK
        assert "access" in response.data

    def test_explicit_web_header_works(self, tenant_basic):
        """
        Login com X-App-Type: web explícito → HTTP 200

        Expectativa: Header 'web' funciona igual a ausência de header
        """
        response = self.client.post(
            self.token_url,
            data={
                "email": "owner@basictenant.com",
                "password": "Test123!@#",
            },
            HTTP_X_APP_TYPE="web",
        )

        assert response.status_code == status.HTTP_200_OK
        assert "access" in response.data

    # ========================================================================
    # ERROR RESPONSE STRUCTURE TESTS
    # ========================================================================

    def test_403_response_has_complete_upgrade_context(self, tenant_basic):
        """
        Verifica estrutura completa da resposta HTTP 403 de upgrade

        Expectativa: Payload estruturado para frontend exibir modal de upgrade
        """
        from users.models import Tenant

        with patch.object(Tenant, "can_use_native_admin", return_value=False):
            response = self.client.post(
                self.token_url,
                data={
                    "email": "owner@basictenant.com",
                    "password": "Test123!@#",
                },
                HTTP_X_APP_TYPE="admin",
            )

        assert response.status_code == status.HTTP_403_FORBIDDEN

        # Required fields
        assert "detail" in response.data
        assert "plan_required" in response.data
        assert "current_plan" in response.data
        assert "upgrade_url" in response.data

        # Values validation
        assert isinstance(response.data["detail"], str)
        assert len(response.data["detail"]) > 0
        assert response.data["plan_required"] in ["pro"]
        assert response.data["current_plan"] in ["basic", "pro"]
        assert response.data["upgrade_url"].startswith("/")

    # ========================================================================
    # EDGE CASES & SECURITY TESTS
    # ========================================================================

    def test_invalid_credentials_returns_401_not_403(self, tenant_basic):
        """
        Credenciais inválidas retornam HTTP 401, não 403

        Expectativa: Validação de plano só ocorre APÓS autenticação bem-sucedida
        """
        response = self.client.post(
            self.token_url,
            data={
                "email": "owner@basictenant.com",
                "password": "WrongPassword!!!",
            },
            HTTP_X_APP_TYPE="admin",
        )

        # Should fail authentication first, not plan validation
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_case_insensitive_app_type_header(self, tenant_basic):
        """
        Header X-App-Type é case-insensitive → 'Admin' = 'admin'

        Expectativa: Backend normaliza header para lowercase
        """
        from users.models import Tenant

        with patch.object(Tenant, "can_use_native_admin", return_value=False):
            response = self.client.post(
                self.token_url,
                data={
                    "email": "owner@basictenant.com",
                    "password": "Test123!@#",
                },
                HTTP_X_APP_TYPE="ADMIN",  # Uppercase
            )

        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert response.data["plan_required"] == "pro"

    def test_unknown_app_type_defaults_to_web(self, tenant_basic):
        """
        Header X-App-Type desconhecido (ex: 'mobile') → trata como web

        Expectativa: Valores não reconhecidos não bloqueiam acesso web
        """
        response = self.client.post(
            self.token_url,
            data={
                "email": "owner@basictenant.com",
                "password": "Test123!@#",
            },
            HTTP_X_APP_TYPE="unknown-app-type",
        )

        # Should allow login (treat as web)
        assert response.status_code == status.HTTP_200_OK
        assert "access" in response.data

    def test_tenant_without_owner_cannot_login(self, db):
        """
        User sem tenant associado não pode fazer login mobile

        Expectativa: HTTP 403 com mensagem apropriada
        """
        user = User.objects.create_user(
            username="orphan_user",
            email="orphan@example.com",
            password="Test123!@#",
        )
        # Explicitly remove tenant assignment (conftest auto-assigns tenant)
        user.tenant = None
        user._tenant_explicitly_none = True  # Prevent conftest from reassigning
        user.save()

        response = self.client.post(
            self.token_url,
            data={
                "email": "orphan@example.com",
                "password": "Test123!@#",
            },
            HTTP_X_APP_TYPE="admin",
        )

        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert "tenant" in response.data["detail"].lower()


@pytest.mark.django_db
class TestMobileAppAccessMetrics:
    """Testes de métricas e logging para acesso mobile"""

    @pytest.fixture(autouse=True)
    def setup(self, api_client):
        from django.core.cache import cache

        cache.clear()  # Limpar throttle cache entre testes
        self.client = api_client
        self.token_url = reverse("token_obtain_pair")

    def test_denied_access_increments_metrics(self, tenant_basic):
        """
        Acesso negado ao Admin App incrementa métrica login_admin_denied

        Expectativa: Prometheus metrics são atualizadas
        """
        from users.observability import USERS_AUTH_EVENTS_TOTAL

        # Get initial metric value
        initial_value = USERS_AUTH_EVENTS_TOTAL.labels(
            event="login_admin_denied", result="failure"
        )._value._value

        # Attempt login (entitlement mockado para exercitar negação)
        from users.models import Tenant

        with patch.object(Tenant, "can_use_native_admin", return_value=False):
            self.client.post(
                self.token_url,
                data={
                    "email": "owner@basictenant.com",
                    "password": "Test123!@#",
                },
                HTTP_X_APP_TYPE="admin",
            )

        # Verify metric incremented
        final_value = USERS_AUTH_EVENTS_TOTAL.labels(
            event="login_admin_denied", result="failure"
        )._value._value

        assert final_value == initial_value + 1

    def test_client_app_denied_increments_correct_metric(self, tenant_basic):
        """
        Acesso negado ao Client App incrementa métrica login_client_denied

        Expectativa: Métricas separadas para admin vs client
        """
        from users.observability import USERS_AUTH_EVENTS_TOTAL

        initial_value = USERS_AUTH_EVENTS_TOTAL.labels(
            event="login_client_denied", result="failure"
        )._value._value

        from users.models import Tenant

        with patch.object(Tenant, "can_use_native_client", return_value=False):
            self.client.post(
                self.token_url,
                data={
                    "email": "owner@basictenant.com",
                    "password": "Test123!@#",
                },
                HTTP_X_APP_TYPE="client",
            )

        final_value = USERS_AUTH_EVENTS_TOTAL.labels(
            event="login_client_denied", result="failure"
        )._value._value

        assert final_value == initial_value + 1
