"""
Testes para validação da permission class RequiresMobileAccess.

BE-MOBILE-SEC-02: Implementa permission class para proteger endpoints
que requerem plano Standard+ para acesso via app nativo.
"""

import pytest
from rest_framework import status
from rest_framework.test import APIClient, APIRequestFactory
from rest_framework.views import APIView
from rest_framework.response import Response
from users.permissions import RequiresMobileAccess
from django.contrib.auth.models import AnonymousUser
from rest_framework.exceptions import PermissionDenied


# Mock View para testar a permissão
class MockMobileView(APIView):
    permission_classes = [RequiresMobileAccess]

    def get(self, request):
        return Response({"status": "ok"})


@pytest.fixture
def api_request_factory():
    return APIRequestFactory()


@pytest.fixture
def tenant_basic(db):
    """Cria tenant com plano Basic (€29/mês) - sem acesso mobile"""
    from users.models import Tenant
    from django.contrib.auth import get_user_model

    User = get_user_model()

    tenant = Tenant.objects.create(
        name="Basic Tenant",
        slug="basic-tenant",
        plan_tier="basic",
    )
    User.objects.create_user(
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
    from django.contrib.auth import get_user_model

    User = get_user_model()

    tenant = Tenant.objects.create(
        name="Pro Tenant",
        slug="pro-tenant",
        plan_tier="pro",
    )
    User.objects.create_user(
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
    from django.contrib.auth import get_user_model

    User = get_user_model()

    tenant = Tenant.objects.create(
        name="Flagged Tenant",
        slug="flagged-tenant",
        plan_tier="basic",
        rn_admin_enabled=True,  # Access granted manually
    )
    User.objects.create_user(
        username="flagged_owner",
        email="owner@flaggedtenant.com",
        password="Test123!@#",
        tenant=tenant,
    )
    return tenant


@pytest.mark.django_db
class TestRequiresMobileAccessPermission:
    """Testes unitários para a permission class RequiresMobileAccess"""

    def test_anonymous_user_is_denied(self, api_request_factory):
        """Usuário anônimo deve ter acesso negado (False)"""
        view = MockMobileView()
        request = api_request_factory.get("/mobile-resource/")
        request.user = AnonymousUser()

        permission = RequiresMobileAccess()
        assert permission.has_permission(request, view) is False

    def test_superuser_is_allowed_regardless_of_tenant(
        self, api_request_factory, django_user_model
    ):
        """Superusuário deve ter acesso permitido sempre"""
        user = django_user_model.objects.create_superuser(
            username="admin", email="admin@example.com", password="password"
        )

        view = MockMobileView()
        request = api_request_factory.get("/mobile-resource/")
        request.user = user

        permission = RequiresMobileAccess()
        assert permission.has_permission(request, view) is True

    def test_user_without_tenant_is_denied(
        self, api_request_factory, django_user_model
    ):
        """Usuário sem tenant deve ter acesso negado"""
        user = django_user_model.objects.create_user(
            username="orphan", email="orphan@example.com", password="password"
        )
        # Garantir que não tem tenant e não é superuser
        user.tenant = None
        # Hack para evitar que o conftest atribua tenant automaticamente
        user._tenant_explicitly_none = True
        user.is_superuser = False
        user.save()

        view = MockMobileView()
        request = api_request_factory.get("/mobile-resource/")
        request.user = user

        permission = RequiresMobileAccess()
        assert permission.has_permission(request, view) is False

    def test_basic_tenant_raises_permission_denied_with_payload(
        self, api_request_factory, tenant_basic, django_user_model
    ):
        """
        Tenant Basic deve levantar PermissionDenied com payload específico de upgrade.
        """
        # Recuperar usuário criado pela fixture tenant_basic
        user = django_user_model.objects.get(email="owner@basictenant.com")

        view = MockMobileView()
        request = api_request_factory.get("/mobile-resource/")
        request.user = user

        permission = RequiresMobileAccess()

        # Deve levantar exceção com detalhes
        with pytest.raises(PermissionDenied) as exc_info:
            permission.has_permission(request, view)

        # Verificar payload da exceção
        error_detail = exc_info.value.detail
        assert error_detail["code"] == "PLAN_UPGRADE_REQUIRED"
        assert error_detail["plan_required"] == "pro"
        assert error_detail["current_plan"] == "basic"
        assert "/pricing" in error_detail["upgrade_url"]

    def test_pro_tenant_is_allowed(
        self, api_request_factory, tenant_pro, django_user_model
    ):
        """Tenant Pro deve ter acesso permitido"""
        user = django_user_model.objects.get(email="owner@protenant.com")

        view = MockMobileView()
        request = api_request_factory.get("/mobile-resource/")
        request.user = user

        permission = RequiresMobileAccess()
        assert permission.has_permission(request, view) is True

    def test_pro_tenant_is_allowed(
        self, api_request_factory, tenant_pro, django_user_model
    ):
        """Tenant Pro deve ter acesso permitido"""
        user = django_user_model.objects.get(email="owner@protenant.com")

        view = MockMobileView()
        request = api_request_factory.get("/mobile-resource/")
        request.user = user

        permission = RequiresMobileAccess()
        assert permission.has_permission(request, view) is True

    def test_basic_tenant_with_admin_flag_is_allowed(
        self, api_request_factory, tenant_with_admin_flag, django_user_model
    ):
        """Tenant Basic com flag rn_admin_enabled=True deve ter acesso permitido"""
        user = django_user_model.objects.get(email="owner@flaggedtenant.com")

        view = MockMobileView()
        request = api_request_factory.get("/mobile-resource/")
        request.user = user

        permission = RequiresMobileAccess()
        assert permission.has_permission(request, view) is True
