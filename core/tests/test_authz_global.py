"""
BE-SEC-01: autorizacao sistemica (autenticacao global).

Todos com tokens JWT reais, sem mock de autenticacao.
"""

import pytest
from django.urls import URLPattern, URLResolver, get_resolver
from rest_framework import status
from rest_framework.test import APIClient, APIRequestFactory
from rest_framework_simplejwt.tokens import RefreshToken

from core.models import SalonCustomer
from core.views import _create_client_jwt_tokens
from users.models import CustomUser, Tenant, TenantStaffMember


def _tenant(slug):
    return Tenant.objects.create(
        name=slug, slug=slug, plan_tier=Tenant.PLAN_BASIC, pwa_client_enabled=True
    )


def _staff(tenant, username, role=TenantStaffMember.Role.OWNER, status_=None):
    user = CustomUser.objects.create_user(
        username=username,
        email=f"{username}@test.com",
        password="pass12345",
        tenant=tenant,
    )
    TenantStaffMember.objects.create(
        tenant=tenant,
        user=user,
        role=role,
        status=status_ or TenantStaffMember.Status.ACTIVE,
    )
    return user


def _staff_refresh(user):
    refresh = RefreshToken.for_user(user)
    refresh["scope"] = "tenant"
    refresh["jwt_version"] = user.jwt_version
    return refresh


def _bearer(api, token):
    api.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
    return api


def _aliasing_client_tokens(staff_user):
    """Token de cliente com user_id == id do staff (cliente de outro tenant)."""
    other = _tenant(f"other-of-{staff_user.id}")
    customer = SalonCustomer.objects.create(
        id=staff_user.id, tenant=other, name="Cliente", email="c@test.com"
    )
    return _create_client_jwt_tokens(other, customer)


def _walk_view_classes(patterns=None):
    patterns = patterns if patterns is not None else get_resolver().url_patterns
    for p in patterns:
        if isinstance(p, URLResolver):
            yield from _walk_view_classes(p.url_patterns)
        elif isinstance(p, URLPattern):
            cb = p.callback
            cls = getattr(cb, "cls", None) or getattr(cb, "view_class", None)
            if cls is not None and hasattr(cls, "authentication_classes"):
                yield cls


@pytest.mark.django_db
class TestClientTokenRejectedByGlobalAuthentication:
    def test_every_authenticated_view_rejects_client_token(self):
        """Varredura: nenhuma view com autenticacao DRF aceita scope=client."""
        staff = _staff(_tenant("sweep"), "sweep-owner")
        tokens = _aliasing_client_tokens(staff)
        request = APIRequestFactory().get(
            "/x/", HTTP_AUTHORIZATION=f"Bearer {tokens['access']}"
        )

        seen = set()
        accepted = []
        for cls in _walk_view_classes():
            if cls in seen:
                continue
            seen.add(cls)
            for auth_cls in cls.authentication_classes:
                try:
                    result = auth_cls().authenticate(request)
                except Exception:
                    continue  # qualquer recusa vale
                if result is not None:
                    accepted.append(f"{cls.__module__}.{cls.__name__}")

        assert len(seen) > 50  # a varredura realmente achou as views
        assert accepted == []

    def test_client_token_aliasing_staff_is_401_on_default_auth_routes(self):
        staff = _staff(_tenant("alias-a"), "alias-owner")
        tokens = _aliasing_client_tokens(staff)
        api = _bearer(APIClient(), tokens["access"])

        for url in (
            "/api/salon/customers/",
            "/api/services/",
            "/api/professionals/",
            "/api/salon/appointments/",
            "/api/salon/forms/",
            "/api/users/me/profile/",
        ):
            resp = api.get(url)
            assert resp.status_code == status.HTTP_401_UNAUTHORIZED, (
                url,
                resp.status_code,
            )

    def test_client_refresh_token_rejected_by_staff_refresh(self):
        staff = _staff(_tenant("refresh-a"), "refresh-owner")
        tokens = _aliasing_client_tokens(staff)
        resp = APIClient().post(
            "/api/users/token/refresh/", {"refresh": tokens["refresh"]}, format="json"
        )
        assert resp.status_code in (401, 403)
        assert "access" not in resp.json()

    def test_staff_token_still_works(self):
        staff = _staff(_tenant("ok-a"), "ok-owner")
        api = _bearer(APIClient(), str(_staff_refresh(staff).access_token))
        assert api.get("/api/salon/customers/").status_code == status.HTTP_200_OK

    def test_client_me_routes_still_accept_client_token(self):
        tenant = _tenant("me-a")
        customer = SalonCustomer.objects.create(
            tenant=tenant, name="Cli", email="cli@test.com"
        )
        tokens = _create_client_jwt_tokens(tenant, customer)
        api = _bearer(APIClient(), tokens["access"])
        resp = api.get("/api/clients/me/appointments/upcoming/")
        assert resp.status_code == status.HTTP_200_OK


@pytest.mark.django_db
class TestDisabledStaffCannotAuthenticate:
    """Politica: desativar o membro corta o acesso (auth + login + refresh)."""

    def _disabled(self, slug):
        tenant = _tenant(slug)
        _staff(tenant, f"{slug}-owner")
        user = _staff(tenant, slug, TenantStaffMember.Role.MANAGER)
        user.staff_member.mark_disabled()
        return user

    def test_existing_access_token_rejected(self):
        user = self._disabled("dis-a")
        api = _bearer(APIClient(), str(_staff_refresh(user).access_token))
        assert api.get("/api/salon/customers/").status_code == 401

    def test_login_rejected(self):
        user = self._disabled("dis-b")
        resp = APIClient().post(
            "/api/users/token/",
            {"email": user.email, "password": "pass12345"},
            format="json",
        )
        assert resp.status_code in (401, 403)
        assert "access" not in resp.json()

    def test_refresh_rejected(self):
        user = self._disabled("dis-c")
        resp = APIClient().post(
            "/api/users/token/refresh/",
            {"refresh": str(_staff_refresh(user))},
            format="json",
        )
        assert resp.status_code in (401, 403)
        assert "access" not in resp.json()

    def test_reactivated_member_can_authenticate_again(self):
        user = self._disabled("dis-d")
        member = user.staff_member
        member.status = TenantStaffMember.Status.ACTIVE
        member.save(update_fields=["status"])
        api = _bearer(APIClient(), str(_staff_refresh(user).access_token))
        assert api.get("/api/salon/customers/").status_code == 200

    def test_user_without_staff_record_still_authenticates(self):
        """Legado/superuser sem TenantStaffMember nao e bloqueado na auth."""
        tenant = _tenant("nostaff-a")
        user = CustomUser.objects.create_user(
            username="ns", email="ns@test.com", password="pass12345", tenant=tenant
        )
        api = _bearer(APIClient(), str(_staff_refresh(user).access_token))
        # autentica (nao 401); a permissao de rota decide depois
        assert api.get("/api/salon/customers/").status_code != 401


# ---------------------------------------------------------------------------
# Varredura de permissoes: toda rota autenticada precisa de uma permissao de
# autorizacao (staff/role) alem de IsAuthenticated, ou estar na allowlist
# abaixo com o motivo. Evita que um endpoint novo nasca so com IsAuthenticated.
# ---------------------------------------------------------------------------

AUTHZ_PERMISSIONS = {
    "IsTenantStaff",
    "IsTenantOwnerOrManager",
    "IsTenantOwner",
    "IsOpsAdmin",
    "IsOpsSupportOrAdmin",
}

# View -> motivo de ficar so com IsAuthenticated (ou equivalente).
ALLOWLIST = {
    # Autoescopo: devolve apenas dados do proprio usuario/tenant autenticado.
    "MeTenantView": "autoescopo (tenant do proprio usuario); 404 sem tenant",
    # Owner ATIVO validado inline (mensagens/metricas fazem parte do contrato).
    "CreateCreditPaymentIntentView": "owner ativo validado inline",
    "CreateCreditCheckoutSessionView": "owner ativo validado inline",
    "StripeSettingsView": "owner ativo validado inline",
    # Conteudo CMS publicado, igual para qualquer usuario autenticado.
    "PublicPageListView": "conteudo CMS publicado",
    "PublicPageDetailView": "conteudo CMS publicado",
    # Raiz do router DRF: so lista links das rotas.
    "APIRootView": "indice do router (sem dados)",
    # Pertence ao Django admin de cache (IsAdminUser).
    "CacheInvalidateView": "IsAdminUser (superuser)",
}


def _permission_names(cls):
    names = set()
    factory = APIRequestFactory()
    for method in ("get", "post", "patch", "delete"):
        view = cls()
        view.request = getattr(factory, method)("/x/")
        view.request.method = method.upper()
        view.action = None
        try:
            perms = view.get_permissions()
        except Exception:
            perms = [p() if isinstance(p, type) else p for p in cls.permission_classes]
        names |= {type(p).__name__ for p in perms}
    return names


@pytest.mark.django_db
def test_every_authenticated_view_has_an_authorization_permission():
    gaps = []
    seen = set()
    for cls in _walk_view_classes():
        if cls in seen or not cls.authentication_classes:
            continue
        seen.add(cls)
        names = _permission_names(cls)
        if "AllowAny" in names or not names:
            continue  # publico (ou sem permissao e autenticacao propria)
        if names & AUTHZ_PERMISSIONS:
            continue
        if cls.__name__ in ALLOWLIST:
            continue
        gaps.append(f"{cls.__module__}.{cls.__name__}: {sorted(names)}")

    assert gaps == [], "Views autenticadas sem permissao de autorizacao:\n" + "\n".join(
        gaps
    )


@pytest.mark.django_db
class TestRoleAndMembershipGates:
    def _api(self, user):
        return _bearer(APIClient(), str(_staff_refresh(user).access_token))

    def test_user_without_staff_record_is_forbidden_on_staff_routes(self):
        tenant = _tenant("gate-a")
        user = CustomUser.objects.create_user(
            username="gate-nostaff",
            email="gate-nostaff@test.com",
            password="pass12345",
            tenant=tenant,
        )
        api = self._api(user)
        for url in (
            "/api/salon/customers/",
            "/api/services/",
            "/api/professionals/",
            "/api/salon/appointments/",
            "/api/reports/overview/",
            "/api/payments/stripe/overview/",
            "/api/inventory/items/",
        ):
            assert api.get(url).status_code == status.HTTP_403_FORBIDDEN, url

    @pytest.mark.parametrize(
        "member_status",
        [TenantStaffMember.Status.INVITED, TenantStaffMember.Status.DISABLED],
    )
    def test_non_active_member_is_denied_on_staff_routes(self, member_status):
        tenant = _tenant(f"gate-{member_status}")
        user = _staff(
            tenant, f"gate-{member_status}", TenantStaffMember.Role.MANAGER, member_status
        )
        api = APIClient()
        api.force_authenticate(user=user)  # ignora a recusa da auth: testa a permissao
        for url in ("/api/salon/customers/", "/api/services/"):
            assert api.get(url).status_code == status.HTTP_403_FORBIDDEN, url

    def test_collaborator_cannot_cancel_or_reactivate_account(self):
        tenant = _tenant("gate-collab")
        _staff(tenant, "gate-collab-owner")
        collab = _staff(tenant, "gate-collab", TenantStaffMember.Role.COLLABORATOR)
        manager = _staff(tenant, "gate-manager", TenantStaffMember.Role.MANAGER)
        for user in (collab, manager):
            api = self._api(user)
            assert (
                api.post("/api/tenants/cancel-account/", {}, format="json").status_code
                == status.HTTP_403_FORBIDDEN
            )
            assert (
                api.post("/api/tenants/reactivate/", {}, format="json").status_code
                == status.HTTP_403_FORBIDDEN
            )

    def test_collaborator_cannot_manage_staff_or_settings(self):
        tenant = _tenant("gate-collab2")
        _staff(tenant, "gate-collab2-owner")
        collab = _staff(tenant, "gate-collab2", TenantStaffMember.Role.COLLABORATOR)
        api = self._api(collab)
        assert api.get("/api/users/staff/").status_code in (200, 403)
        assert (
            api.patch(
                "/api/users/tenant/meta/", {"app_name": "X"}, format="json"
            ).status_code
            == status.HTTP_403_FORBIDDEN
        )
        assert (
            api.patch(
                "/api/users/tenant/profile/", {"name": "X"}, format="json"
            ).status_code
            == status.HTTP_403_FORBIDDEN
        )

    def test_staff_of_another_tenant_has_no_access(self):
        tenant_a = _tenant("gate-iso-a")
        other = _tenant("gate-iso-b")
        user = CustomUser.objects.create_user(
            username="gate-iso",
            email="gate-iso@test.com",
            password="pass12345",
            tenant=tenant_a,
        )
        TenantStaffMember.objects.create(
            tenant=other, user=user, role=TenantStaffMember.Role.OWNER
        )
        api = self._api(user)
        assert api.get("/api/salon/customers/").status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.django_db
def test_tenant_isolation_mixin_has_no_test_database_bypass(monkeypatch):
    """O isolamento nao pode ser desligado pelo nome do banco (BE-SEC-01)."""
    from types import SimpleNamespace

    from core.mixins import TenantIsolatedMixin
    from core.models import Service

    tenant_a = _tenant("mixin-a")
    tenant_b = _tenant("mixin-b")
    owner_a = _staff(tenant_a, "mixin-owner-a")
    owner_b = _staff(tenant_b, "mixin-owner-b")
    Service.objects.create(
        tenant=tenant_a, user=owner_a, name="A", duration_minutes=30, price_eur="10"
    )
    Service.objects.create(
        tenant=tenant_b, user=owner_b, name="B", duration_minutes=30, price_eur="10"
    )

    class _Base:
        def get_queryset(self):
            return Service.objects.all()

    class _View(TenantIsolatedMixin, _Base):
        pass

    from django.conf import settings

    monkeypatch.setitem(settings.DATABASES["default"], "NAME", "test_whatever")
    view = _View()
    view.request = SimpleNamespace(user=owner_a, tenant=tenant_a)

    assert list(view.get_queryset().values_list("name", flat=True)) == ["A"]


@pytest.mark.django_db
class TestBillingReadsAreOwnerOrManagerOnly:
    """BE-SEC-01: visao geral e historico de cobranca nao vao para colaborador."""

    URLS = ("/api/payments/stripe/overview/", "/api/payments/stripe/history/")

    def _api(self, user):
        return _bearer(APIClient(), str(_staff_refresh(user).access_token))

    def test_collaborator_is_forbidden(self):
        tenant = _tenant("bill-a")
        _staff(tenant, "bill-a-owner")
        collab = _staff(tenant, "bill-a-collab", TenantStaffMember.Role.COLLABORATOR)
        api = self._api(collab)
        for url in self.URLS:
            assert api.get(url).status_code == status.HTTP_403_FORBIDDEN, url

    @pytest.mark.parametrize(
        "role", [TenantStaffMember.Role.OWNER, TenantStaffMember.Role.MANAGER]
    )
    def test_owner_and_manager_are_allowed(self, role):
        tenant = _tenant(f"bill-{role}")
        if role != TenantStaffMember.Role.OWNER:
            _staff(tenant, f"bill-{role}-owner")
        user = _staff(tenant, f"bill-{role}", role)
        api = self._api(user)
        for url in self.URLS:
            assert api.get(url).status_code == status.HTTP_200_OK, url
