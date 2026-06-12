"""
Testes para a permission class RequiresMobileAccess.

BE-SEC-01: Padronizar autorização mobile por app_type em endpoints críticos.
A permissão avalia o header X-App-Type (admin/client/web) e verifica o
entitlement do tenant antes de conceder acesso.
"""

from unittest.mock import patch

import pytest
from django.contrib.auth.models import AnonymousUser
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response
from rest_framework.test import APIRequestFactory
from rest_framework.views import APIView

from users.permissions import RequiresMobileAccess


class MockMobileView(APIView):
    permission_classes = [RequiresMobileAccess]

    def get(self, request):
        return Response({"status": "ok"})


@pytest.fixture
def factory():
    return APIRequestFactory()


@pytest.fixture
def tenant_basic(db):
    """Tenant Basic — sem entitlement para nenhum app nativo."""
    from django.contrib.auth import get_user_model

    from users.models import Tenant

    User = get_user_model()
    tenant = Tenant.objects.create(
        name="Basic Tenant", slug="basic-tenant", plan_tier="basic"
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
    """Tenant Pro — Admin + Client Apps habilitados por plano."""
    from django.contrib.auth import get_user_model

    from users.models import Tenant

    User = get_user_model()
    tenant = Tenant.objects.create(
        name="Pro Tenant", slug="pro-tenant", plan_tier="pro"
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
    """Tenant Basic com rn_admin_enabled=True — acesso manual ao Admin App."""
    from django.contrib.auth import get_user_model

    from users.models import Tenant

    User = get_user_model()
    tenant = Tenant.objects.create(
        name="Admin-Flagged Tenant",
        slug="admin-flagged-tenant",
        plan_tier="basic",
        rn_admin_enabled=True,
    )
    User.objects.create_user(
        username="admin_flagged_owner",
        email="owner@adminflagged.com",
        password="Test123!@#",
        tenant=tenant,
    )
    return tenant


@pytest.fixture
def tenant_with_client_flag(db):
    """Tenant Basic com rn_client_enabled=True — acesso manual ao Client App."""
    from django.contrib.auth import get_user_model

    from users.models import Tenant

    User = get_user_model()
    tenant = Tenant.objects.create(
        name="Client-Flagged Tenant",
        slug="client-flagged-tenant",
        plan_tier="basic",
        rn_client_enabled=True,
    )
    User.objects.create_user(
        username="client_flagged_owner",
        email="owner@clientflagged.com",
        password="Test123!@#",
        tenant=tenant,
    )
    return tenant


def _make_request(factory, app_type=None):
    """Cria GET request com ou sem header X-App-Type."""
    if app_type:
        return factory.get("/mobile-resource/", HTTP_X_APP_TYPE=app_type)
    return factory.get("/mobile-resource/")


@pytest.mark.django_db
class TestRequiresMobileAccessPermission:
    """Testes unitários para RequiresMobileAccess."""

    # ------------------------------------------------------------------
    # Casos base — usuário/tenant inválidos
    # ------------------------------------------------------------------

    def test_anonymous_user_is_denied(self, factory):
        """Usuário anônimo deve ser negado independente do header."""
        view = MockMobileView()
        request = _make_request(factory, app_type="admin")
        request.user = AnonymousUser()
        assert RequiresMobileAccess().has_permission(request, view) is False

    def test_user_without_tenant_is_denied(self, factory, django_user_model):
        """Usuário autenticado sem tenant deve ser negado."""
        user = django_user_model.objects.create_user(
            username="orphan", email="orphan@example.com", password="password"
        )
        user.tenant = None
        user._tenant_explicitly_none = True
        user.is_superuser = False
        user.save()

        request = _make_request(factory, app_type="admin")
        request.user = user
        assert RequiresMobileAccess().has_permission(request, MockMobileView()) is False

    def test_superuser_is_always_allowed(self, factory, django_user_model):
        """Superusuário deve ter acesso para qualquer app_type."""
        user = django_user_model.objects.create_superuser(
            username="su", email="su@example.com", password="password"
        )
        for app_type in ("admin", "client", "web"):
            request = _make_request(factory, app_type=app_type)
            request.user = user
            assert (
                RequiresMobileAccess().has_permission(request, MockMobileView()) is True
            )

    # ------------------------------------------------------------------
    # Web / header ausente — sem restrição de entitlement
    # ------------------------------------------------------------------

    def test_basic_tenant_web_is_allowed(
        self, factory, tenant_basic, django_user_model
    ):
        """Basic sem header (web) deve passar — sem restrição mobile."""
        user = django_user_model.objects.get(email="owner@basictenant.com")
        request = _make_request(factory)  # sem header
        request.user = user
        assert RequiresMobileAccess().has_permission(request, MockMobileView()) is True

    def test_basic_tenant_explicit_web_header_is_allowed(
        self, factory, tenant_basic, django_user_model
    ):
        """Basic com X-App-Type: web explícito deve passar."""
        user = django_user_model.objects.get(email="owner@basictenant.com")
        request = _make_request(factory, app_type="web")
        request.user = user
        assert RequiresMobileAccess().has_permission(request, MockMobileView()) is True

    # ------------------------------------------------------------------
    # Admin App — X-App-Type: admin
    # ------------------------------------------------------------------

    def test_basic_tenant_admin_app_is_allowed(
        self, factory, tenant_basic, django_user_model
    ):
        """BE-PLANS-01 (#481): Basic absorveu apps nativos; admin liberado."""
        user = django_user_model.objects.get(email="owner@basictenant.com")
        request = _make_request(factory, app_type="admin")
        request.user = user
        assert RequiresMobileAccess().has_permission(request, MockMobileView()) is True

    def test_tenant_without_entitlement_admin_app_is_denied_with_payload(
        self, factory, tenant_basic, django_user_model
    ):
        """Sem entitlement (mockado), X-App-Type: admin deve levantar 403 com payload."""
        from users.models import Tenant

        user = django_user_model.objects.get(email="owner@basictenant.com")
        request = _make_request(factory, app_type="admin")
        request.user = user

        with patch.object(Tenant, "can_use_native_admin", return_value=False), \
                pytest.raises(PermissionDenied) as exc_info:
            RequiresMobileAccess().has_permission(request, MockMobileView())

        detail = exc_info.value.detail
        assert detail["code"] == "PLAN_UPGRADE_REQUIRED"
        assert detail["plan_required"] == "pro"
        assert detail["current_plan"] == "basic"
        assert "/pricing" in detail["upgrade_url"]
        assert "Admin App" in detail["detail"]

    def test_pro_tenant_admin_app_is_allowed(
        self, factory, tenant_pro, django_user_model
    ):
        """Pro com X-App-Type: admin deve ter acesso."""
        user = django_user_model.objects.get(email="owner@protenant.com")
        request = _make_request(factory, app_type="admin")
        request.user = user
        assert RequiresMobileAccess().has_permission(request, MockMobileView()) is True

    def test_basic_tenant_with_admin_flag_is_allowed(
        self, factory, tenant_with_admin_flag, django_user_model
    ):
        """Basic com rn_admin_enabled=True e X-App-Type: admin deve ter acesso."""
        user = django_user_model.objects.get(email="owner@adminflagged.com")
        request = _make_request(factory, app_type="admin")
        request.user = user
        assert RequiresMobileAccess().has_permission(request, MockMobileView()) is True

    # ------------------------------------------------------------------
    # Client App — X-App-Type: client
    # ------------------------------------------------------------------

    def test_basic_tenant_client_app_is_allowed_by_plan(
        self, factory, tenant_basic, django_user_model
    ):
        """BE-PLANS-01 (#481): Basic absorveu apps nativos; client liberado."""
        user = django_user_model.objects.get(email="owner@basictenant.com")
        request = _make_request(factory, app_type="client")
        request.user = user
        assert RequiresMobileAccess().has_permission(request, MockMobileView()) is True

    def test_tenant_without_entitlement_client_app_is_denied_with_payload(
        self, factory, tenant_basic, django_user_model
    ):
        """Sem entitlement (mockado), X-App-Type: client deve levantar 403 com payload."""
        from users.models import Tenant

        user = django_user_model.objects.get(email="owner@basictenant.com")
        request = _make_request(factory, app_type="client")
        request.user = user

        with patch.object(Tenant, "can_use_native_client", return_value=False), \
                pytest.raises(PermissionDenied) as exc_info:
            RequiresMobileAccess().has_permission(request, MockMobileView())

        detail = exc_info.value.detail
        assert detail["code"] == "PLAN_UPGRADE_REQUIRED"
        assert detail["plan_required"] == "pro"
        assert detail["current_plan"] == "basic"
        assert "/pricing" in detail["upgrade_url"]
        assert "Client App" in detail["detail"]

    def test_pro_tenant_client_app_is_allowed(
        self, factory, tenant_pro, django_user_model
    ):
        """Pro com X-App-Type: client deve ter acesso."""
        user = django_user_model.objects.get(email="owner@protenant.com")
        request = _make_request(factory, app_type="client")
        request.user = user
        assert RequiresMobileAccess().has_permission(request, MockMobileView()) is True

    def test_basic_tenant_with_client_flag_is_allowed(
        self, factory, tenant_with_client_flag, django_user_model
    ):
        """Basic com rn_client_enabled=True e X-App-Type: client deve ter acesso."""
        user = django_user_model.objects.get(email="owner@clientflagged.com")
        request = _make_request(factory, app_type="client")
        request.user = user
        assert RequiresMobileAccess().has_permission(request, MockMobileView()) is True

    # ------------------------------------------------------------------
    # Payload diferenciado por app_type
    # ------------------------------------------------------------------

    def test_admin_and_client_payloads_are_distinct(
        self, factory, tenant_basic, django_user_model
    ):
        """Mensagem de erro deve diferenciar Admin App de Client App."""
        from users.models import Tenant

        user = django_user_model.objects.get(email="owner@basictenant.com")

        request_admin = _make_request(factory, app_type="admin")
        request_admin.user = user
        with patch.object(Tenant, "can_use_native_admin", return_value=False), \
                pytest.raises(PermissionDenied) as admin_exc:
            RequiresMobileAccess().has_permission(request_admin, MockMobileView())

        request_client = _make_request(factory, app_type="client")
        request_client.user = user
        with patch.object(Tenant, "can_use_native_client", return_value=False), \
                pytest.raises(PermissionDenied) as client_exc:
            RequiresMobileAccess().has_permission(request_client, MockMobileView())

        assert admin_exc.value.detail["detail"] != client_exc.value.detail["detail"]

    # ------------------------------------------------------------------
    # Case-insensitive
    # ------------------------------------------------------------------

    def test_app_type_header_is_case_insensitive(
        self, factory, tenant_basic, django_user_model
    ):
        """X-App-Type: ADMIN (maiúsculo) deve ser tratado igual a admin."""
        from users.models import Tenant

        user = django_user_model.objects.get(email="owner@basictenant.com")
        request = _make_request(factory, app_type="ADMIN")
        request.user = user

        with patch.object(Tenant, "can_use_native_admin", return_value=False), \
                pytest.raises(PermissionDenied) as exc_info:
            RequiresMobileAccess().has_permission(request, MockMobileView())

        assert exc_info.value.detail["code"] == "PLAN_UPGRADE_REQUIRED"
