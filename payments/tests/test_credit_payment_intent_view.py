import json
import pytest
from decimal import Decimal
from rest_framework import status
from rest_framework.test import APIClient

from payments.models import CreditPayment


@pytest.fixture
def auth_client(db):
    from users.models import CustomUser

    def _make(user=None):
        if user is None:
            user = CustomUser.objects.create_user(
                username="credit_pi_user",
                email="credit_pi_user@example.com",
                password="pass",
            )
        c = APIClient()
        c.force_authenticate(user=user)
        return c, user

    return _make


def _setup_price_ids(monkeypatch, settings):
    # Configurar price IDs de créditos para o ambiente de teste
    settings.STRIPE_PRICE_CREDITS_5_ID = "price_credits_5_test"
    settings.STRIPE_PRICE_CREDITS_10_ID = "price_credits_10_test"
    settings.STRIPE_PRICE_CREDITS_25_ID = "price_credits_25_test"
    settings.STRIPE_PRICE_CREDITS_50_ID = "price_credits_50_test"
    settings.STRIPE_PRICE_CREDITS_100_ID = "price_credits_100_test"

    # Ajustar o mapa estático para refletir os price IDs de teste
    from payments.services import CreditPurchaseService
    monkeypatch.setattr(
        CreditPurchaseService,
        "PRICE_TO_CREDITS",
        {
            settings.STRIPE_PRICE_CREDITS_5_ID: Decimal("5.00"),
            settings.STRIPE_PRICE_CREDITS_10_ID: Decimal("10.00"),
            settings.STRIPE_PRICE_CREDITS_25_ID: Decimal("25.00"),
            settings.STRIPE_PRICE_CREDITS_50_ID: Decimal("50.00"),
            settings.STRIPE_PRICE_CREDITS_100_ID: Decimal("100.00"),
        },
        raising=True,
    )


def _patch_stripe(monkeypatch):
    import payments.services as payments_services
    import payments.stripe_utils as stripe_utils

    class _StripePaymentIntent:
        last_kwargs = None

        @staticmethod
        def create(**kwargs):
            _StripePaymentIntent.last_kwargs = kwargs
            return type(
                "PaymentIntentObj",
                (),
                {
                    "client_secret": "pi_secret_test_abc",
                    "id": "pi_test_abc",
                    "amount": kwargs.get("amount", 0),
                    "currency": kwargs.get("currency", "eur"),
                },
            )

    class _StripeCustomer:
        @staticmethod
        def create(**kwargs):
            return {"id": "cus_test_pi"}

    class _StripeSDK:
        PaymentIntent = _StripePaymentIntent
        Customer = _StripeCustomer

    monkeypatch.setattr(payments_services, "stripe", _StripeSDK, raising=True)
    monkeypatch.setattr(stripe_utils, "get_stripe", lambda: _StripeSDK, raising=True)

    return _StripePaymentIntent


@pytest.mark.django_db
def test_available_credit_packages_authenticated_returns_expected(auth_client, monkeypatch, settings):
    _setup_price_ids(monkeypatch, settings)

    client, user = auth_client()

    resp = client.get("/api/payments/stripe/credits/packages/")
    assert resp.status_code == status.HTTP_200_OK
    data = resp.data["packages"] if isinstance(resp.data, dict) else resp.data.get("packages")
    assert isinstance(data, list)
    assert len(data) == 5

    # validar que cada pacote tem credits e price_id esperado
    ids = {p["price_id"] for p in data}
    assert ids == {
        settings.STRIPE_PRICE_CREDITS_5_ID,
        settings.STRIPE_PRICE_CREDITS_10_ID,
        settings.STRIPE_PRICE_CREDITS_25_ID,
        settings.STRIPE_PRICE_CREDITS_50_ID,
        settings.STRIPE_PRICE_CREDITS_100_ID,
    }

    credits = {str(p["credits"]) for p in data}
    assert credits == {"5.00", "10.00", "25.00", "50.00", "100.00"}


@pytest.mark.django_db
def test_endpoints_require_authentication_returns_401(monkeypatch, settings):
    _setup_price_ids(monkeypatch, settings)
    # Cliente não autenticado
    client = APIClient()

    # Pacotes
    resp_pkg = client.get("/api/payments/stripe/credits/packages/")
    assert resp_pkg.status_code == status.HTTP_401_UNAUTHORIZED

    # Intent
    resp_pi = client.post("/api/payments/stripe/credits/purchase/", {"amount_eur": 5.0}, format="json")
    assert resp_pi.status_code == status.HTTP_401_UNAUTHORIZED


    


@pytest.mark.django_db
def test_purchase_stripe_error_bubbles_as_400(auth_client, monkeypatch, settings):
    _setup_price_ids(monkeypatch, settings)
    _patch_stripe(monkeypatch)

    client, user = auth_client()
    # Tornar usuário OWNER ativo
    from users.models import TenantStaffMember
    TenantStaffMember.objects.create(
        tenant=user.tenant,
        user=user,
        role=TenantStaffMember.Role.OWNER,
        status=TenantStaffMember.Status.ACTIVE,
    )
    user.tenant.comm_extra_allowed = True
    user.tenant.save(update_fields=["comm_extra_allowed"])

    # Forçar erro na criação do PaymentIntent
    import payments.services as payments_services

    def _raise(*args, **kwargs):
        raise Exception("Stripe simulated error")

    monkeypatch.setattr(
        payments_services.StripePaymentService,
        "create_credit_payment_intent",
        _raise,
        raising=True,
    )

    resp = client.post("/api/payments/stripe/credits/purchase/", {"amount_eur": 5.0}, format="json")
    assert resp.status_code == status.HTTP_400_BAD_REQUEST
    assert "simulated" in (resp.data.get("detail", "") or "")

def test_purchase_forbidden_when_extra_disabled_returns_403_no_pi_created(
    auth_client, monkeypatch, settings
):
    _setup_price_ids(monkeypatch, settings)
    _patch_stripe(monkeypatch)

    client, user = auth_client()
    # Tornar usuário OWNER ativo
    from users.models import TenantStaffMember
    TenantStaffMember.objects.create(
        tenant=user.tenant,
        user=user,
        role=TenantStaffMember.Role.OWNER,
        status=TenantStaffMember.Status.ACTIVE,
    )
    # Desabilitar compra de créditos avulsos
    user.tenant.comm_extra_allowed = False
    user.tenant.save(update_fields=["comm_extra_allowed"])

    purchase_url = "/api/payments/stripe/credits/purchase/"
    resp = client.post(purchase_url, {"amount_eur": 5.0}, format="json")
    assert resp.status_code == status.HTTP_403_FORBIDDEN
    assert "não permitida" in (resp.data.get("detail", "") or "")

    # Garantir que nenhum CreditPayment foi criado
    assert not CreditPayment.objects.filter(user=user, tenant=user.tenant).exists()


@pytest.mark.django_db
@pytest.mark.parametrize(
    "amount_eur,expected_cents",
    [
        (5.0, 500),
        (10.0, 1000),
        (25.0, 2500),
        (50.0, 5000),
        (100.0, 10000),
    ],
)
def test_purchase_intent_supported_amounts_success_and_amount_cents(
    auth_client, monkeypatch, settings, amount_eur, expected_cents
):
    _setup_price_ids(monkeypatch, settings)
    StripePI = _patch_stripe(monkeypatch)

    client, user = auth_client()
    # Tornar usuário OWNER ativo
    from users.models import TenantStaffMember
    TenantStaffMember.objects.create(
        tenant=user.tenant,
        user=user,
        role=TenantStaffMember.Role.OWNER,
        status=TenantStaffMember.Status.ACTIVE,
    )
    # Habilitar compra de créditos avulsos
    user.tenant.comm_extra_allowed = True
    user.tenant.save(update_fields=["comm_extra_allowed"])

    purchase_url = "/api/payments/stripe/credits/purchase/"
    resp = client.post(purchase_url, {"amount_eur": amount_eur}, format="json")
    assert resp.status_code == status.HTTP_200_OK
    assert resp.data.get("payment_intent_id") == "pi_test_abc"

    # Verificar que o Stripe recebeu o valor correto em centavos
    assert StripePI.last_kwargs is not None
    assert StripePI.last_kwargs.get("amount") == expected_cents
    assert StripePI.last_kwargs.get("currency") == "eur"


@pytest.mark.django_db
def test_purchase_intent_invalid_amount_returns_400(auth_client, monkeypatch, settings):
    _setup_price_ids(monkeypatch, settings)
    _patch_stripe(monkeypatch)

    client, user = auth_client()
    # Tornar usuário OWNER ativo
    from users.models import TenantStaffMember
    TenantStaffMember.objects.create(
        tenant=user.tenant,
        user=user,
        role=TenantStaffMember.Role.OWNER,
        status=TenantStaffMember.Status.ACTIVE,
    )
    user.tenant.comm_extra_allowed = True
    user.tenant.save(update_fields=["comm_extra_allowed"])

    purchase_url = "/api/payments/stripe/credits/purchase/"
    resp = client.post(purchase_url, {"amount_eur": 7.5}, format="json")
    assert resp.status_code == status.HTTP_400_BAD_REQUEST
    assert "Valor não suportado" in (resp.data.get("detail", "") or "")


@pytest.mark.django_db
def test_purchase_forbidden_when_role_not_owner_returns_403(auth_client, monkeypatch, settings):
    _setup_price_ids(monkeypatch, settings)
    _patch_stripe(monkeypatch)

    client, user = auth_client()
    from users.models import TenantStaffMember
    # Criar staff como MANAGER (não OWNER)
    TenantStaffMember.objects.create(
        tenant=user.tenant,
        user=user,
        role=TenantStaffMember.Role.MANAGER,
        status=TenantStaffMember.Status.ACTIVE,
    )
    user.tenant.comm_extra_allowed = True
    user.tenant.save(update_fields=["comm_extra_allowed"])

    resp = client.post("/api/payments/stripe/credits/purchase/", {"amount_eur": 5.0}, format="json")
    assert resp.status_code == status.HTTP_403_FORBIDDEN
    assert "apenas OWNER ativo" in (resp.data.get("detail", "") or "")


@pytest.mark.django_db
def test_purchase_forbidden_when_staff_inactive_returns_403(auth_client, monkeypatch, settings):
    _setup_price_ids(monkeypatch, settings)
    _patch_stripe(monkeypatch)

    client, user = auth_client()
    from users.models import TenantStaffMember
    # Criar staff OWNER porém INACTIVE (invited)
    TenantStaffMember.objects.create(
        tenant=user.tenant,
        user=user,
        role=TenantStaffMember.Role.OWNER,
        status=TenantStaffMember.Status.INVITED,
    )
    user.tenant.comm_extra_allowed = True
    user.tenant.save(update_fields=["comm_extra_allowed"])

    resp = client.post("/api/payments/stripe/credits/purchase/", {"amount_eur": 5.0}, format="json")
    assert resp.status_code == status.HTTP_403_FORBIDDEN
    assert "apenas OWNER ativo" in (resp.data.get("detail", "") or "")


@pytest.mark.django_db
def test_purchase_success_for_active_owner_returns_200(auth_client, monkeypatch, settings):
    _setup_price_ids(monkeypatch, settings)
    _patch_stripe(monkeypatch)

    client, user = auth_client()
    from users.models import TenantStaffMember
    # Criar OWNER ativo
    TenantStaffMember.objects.create(
        tenant=user.tenant,
        user=user,
        role=TenantStaffMember.Role.OWNER,
        status=TenantStaffMember.Status.ACTIVE,
    )
    user.tenant.comm_extra_allowed = True
    user.tenant.save(update_fields=["comm_extra_allowed"])

    resp = client.post("/api/payments/stripe/credits/purchase/", {"amount_eur": 5.0}, format="json")
    assert resp.status_code == status.HTTP_200_OK
    assert resp.data.get("payment_intent_id") == "pi_test_abc"


@pytest.mark.django_db
def test_purchase_forbidden_when_user_has_no_tenant_returns_403(monkeypatch, settings):
    _setup_price_ids(monkeypatch, settings)
    _patch_stripe(monkeypatch)

    from users.models import CustomUser
    client = APIClient()
    # Criar usuário explicitamente sem tenant
    user = CustomUser(username="no_tenant_user", email="no_tenant@example.com")
    setattr(user, "_tenant_explicitly_none", True)
    user.set_password("pass")
    user.save()
    # Garantir que permaneça sem tenant mesmo após quaisquer patches
    from django.contrib.auth import get_user_model
    get_user_model().objects.filter(id=user.id).update(tenant=None)
    user.refresh_from_db()
    # Remover qualquer staff ligado (por segurança)
    from users.models import TenantStaffMember
    TenantStaffMember.objects.filter(user=user).delete()
    client.force_authenticate(user=user)

    resp = client.post("/api/payments/stripe/credits/purchase/", {"amount_eur": 5.0}, format="json")
    assert resp.status_code == status.HTTP_403_FORBIDDEN
    assert "usuário sem tenant" in (resp.data.get("detail", "") or "")


@pytest.mark.django_db
def test_purchase_forbidden_when_request_tenant_differs_returns_403(auth_client, monkeypatch, settings):
    _setup_price_ids(monkeypatch, settings)
    _patch_stripe(monkeypatch)

    client, user = auth_client()
    from users.models import Tenant, TenantStaffMember
    # OWNER ativo
    TenantStaffMember.objects.create(
        tenant=user.tenant,
        user=user,
        role=TenantStaffMember.Role.OWNER,
        status=TenantStaffMember.Status.ACTIVE,
    )
    user.tenant.comm_extra_allowed = True
    user.tenant.save(update_fields=["comm_extra_allowed"])

    # Criar tenant diferente e forçar middleware a usar este tenant
    other_tenant = Tenant.objects.create(name="Other Salon", slug="other-salon")

    import core.middleware as core_mw

    def mock_mw(get_response):
        def _mw(request):
            request.tenant = other_tenant
            return get_response(request)
        return _mw

    monkeypatch.setattr(core_mw, "TenantMiddleware", mock_mw, raising=True)

    resp = client.post("/api/payments/stripe/credits/purchase/", {"amount_eur": 5.0}, format="json")
    assert resp.status_code == status.HTTP_403_FORBIDDEN
    assert "tenant de requisição não corresponde" in (resp.data.get("detail", "") or "")