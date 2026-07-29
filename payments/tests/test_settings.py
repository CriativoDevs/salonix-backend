import pytest
from rest_framework.test import APIClient
from prometheus_client import REGISTRY

from users.models import CustomUser, Tenant, TenantStaffMember


def _metric_value(label: str) -> float:
    value = REGISTRY.get_sample_value(
        "payments_settings_updated_total", {"result": label}
    )
    return float(value or 0.0)


@pytest.fixture
def owner_user(db):
    tenant = Tenant.objects.create(
        name="Salon", slug="salon", plan_tier=Tenant.PLAN_PRO
    )
    user = CustomUser.objects.create_user(
        username="owner", email="owner@example.com", password="pass", tenant=tenant
    )
    TenantStaffMember.objects.create(
        tenant=tenant, user=user, role=TenantStaffMember.Role.OWNER
    )
    return user


@pytest.fixture
def manager_user(db):
    tenant = Tenant.objects.create(
        name="Salon2", slug="salon2", plan_tier=Tenant.PLAN_PRO
    )
    user = CustomUser.objects.create_user(
        username="manager", email="manager@example.com", password="pass", tenant=tenant
    )
    TenantStaffMember.objects.create(
        tenant=tenant, user=user, role=TenantStaffMember.Role.MANAGER
    )
    return user


@pytest.mark.django_db
def test_settings_patch_owner_success_updates_comm_auto_renew_and_metric(
    owner_user, settings
):
    settings.STRIPE_PRICE_CREDITS_10_ID = "price_credits_10_test"

    c = APIClient()
    c.force_authenticate(user=owner_user)

    # baseline metrics
    before_success = _metric_value("success")

    # ensure starting value is False
    owner_user.tenant.comm_auto_renew = False
    owner_user.tenant.save(update_fields=["comm_auto_renew"])

    resp = c.patch(
        "/api/payments/stripe/settings/",
        {"auto_renewal": True, "auto_renewal_price_id": "price_credits_10_test"},
        format="json",
    )
    assert resp.status_code == 200
    assert resp.data["auto_renewal"] is True

    owner_user.tenant.refresh_from_db()
    assert owner_user.tenant.comm_auto_renew is True

    after_success = _metric_value("success")
    assert after_success == before_success + 1


@pytest.mark.django_db
def test_settings_patch_forbidden_when_not_owner_increments_metric(manager_user):
    c = APIClient()
    c.force_authenticate(user=manager_user)

    before_forbidden = _metric_value("forbidden")

    resp = c.patch(
        "/api/payments/stripe/settings/", {"auto_renewal": True}, format="json"
    )
    assert resp.status_code == 403
    assert "Permissão negada" in str(resp.data.get("detail", "")) or resp.data

    after_forbidden = _metric_value("forbidden")
    assert after_forbidden == before_forbidden + 1


@pytest.mark.django_db
def test_settings_patch_invalid_payload_increments_metric(owner_user):
    c = APIClient()
    c.force_authenticate(user=owner_user)

    before_invalid = _metric_value("invalid")

    # missing required field
    resp = c.patch("/api/payments/stripe/settings/", {}, format="json")
    assert resp.status_code == 400

    after_invalid = _metric_value("invalid")
    assert after_invalid == before_invalid + 1


@pytest.mark.django_db
def test_settings_patch_forbidden_when_user_without_tenant_increments_metric(db):
    user = CustomUser.objects.create_user(
        username="notenant", email="notenant@example.com", password="pass"
    )
    c = APIClient()
    c.force_authenticate(user=user)

    before_forbidden = _metric_value("forbidden")

    resp = c.patch(
        "/api/payments/stripe/settings/", {"auto_renewal": True}, format="json"
    )
    assert resp.status_code == 403
    assert "Usuário sem tenant" in str(resp.data.get("detail", "")) or resp.data

    after_forbidden = _metric_value("forbidden")
    assert after_forbidden == before_forbidden + 1


@pytest.mark.django_db
def test_billing_overview_reflects_auto_renewal_after_update(owner_user, settings):
    settings.STRIPE_PRICE_CREDITS_10_ID = "price_credits_10_test"

    c = APIClient()
    c.force_authenticate(user=owner_user)

    # Set False then update to True
    owner_user.tenant.comm_auto_renew = False
    owner_user.tenant.save(update_fields=["comm_auto_renew"])

    resp_patch = c.patch(
        "/api/payments/stripe/settings/",
        {"auto_renewal": True, "auto_renewal_price_id": "price_credits_10_test"},
        format="json",
    )
    assert resp_patch.status_code == 200

    resp_overview = c.get("/api/payments/stripe/overview/")
    assert resp_overview.status_code == 200
    assert resp_overview.data.get("has_auto_renewal") is True


@pytest.mark.django_db
def test_settings_patch_emits_audit_log_on_change(owner_user, monkeypatch, settings):
    settings.STRIPE_PRICE_CREDITS_10_ID = "price_credits_10_test"

    c = APIClient()
    c.force_authenticate(user=owner_user)

    owner_user.tenant.comm_auto_renew = False
    owner_user.tenant.save(update_fields=["comm_auto_renew"])

    # Patch o logger para capturar a chamada
    from payments import views as payments_views

    captured = {"msg": None, "extra": None}

    def fake_info(msg, *args, **kwargs):
        captured["msg"] = msg
        captured["extra"] = kwargs.get("extra")

    def fake_error(*args, **kwargs):
        return None

    monkeypatch.setattr(
        payments_views,
        "logger",
        type(
            "_L",
            (),
            {"info": staticmethod(fake_info), "error": staticmethod(fake_error)},
        ),
    )

    resp = c.patch(
        "/api/payments/stripe/settings/",
        {"auto_renewal": True, "auto_renewal_price_id": "price_credits_10_test"},
        format="json",
    )
    assert resp.status_code == 200
    assert captured["msg"] == "payments.settings.update"
    assert isinstance(captured["extra"], dict)
    assert {
        "actor_id",
        "tenant_id",
        "field",
        "old_value",
        "new_value",
    }.issubset(set(captured["extra"].keys()))


@pytest.mark.django_db
def test_settings_patch_requires_price_id_when_enabling_auto_renewal(
    owner_user, settings
):
    settings.STRIPE_PRICE_CREDITS_10_ID = "price_credits_10_test"

    c = APIClient()
    c.force_authenticate(user=owner_user)

    resp = c.patch(
        "/api/payments/stripe/settings/", {"auto_renewal": True}, format="json"
    )
    assert resp.status_code == 400
    assert "auto_renewal_price_id" in resp.data


@pytest.mark.django_db
def test_settings_patch_rejects_unknown_price_id(owner_user, settings):
    settings.STRIPE_PRICE_CREDITS_10_ID = "price_credits_10_test"

    c = APIClient()
    c.force_authenticate(user=owner_user)

    resp = c.patch(
        "/api/payments/stripe/settings/",
        {"auto_renewal": True, "auto_renewal_price_id": "price_unknown"},
        format="json",
    )
    assert resp.status_code == 400
    assert "auto_renewal_price_id" in resp.data


@pytest.mark.django_db
def test_settings_patch_saves_price_id_when_enabling_auto_renewal(
    owner_user, settings
):
    settings.STRIPE_PRICE_CREDITS_10_ID = "price_credits_10_test"

    c = APIClient()
    c.force_authenticate(user=owner_user)

    resp = c.patch(
        "/api/payments/stripe/settings/",
        {"auto_renewal": True, "auto_renewal_price_id": "price_credits_10_test"},
        format="json",
    )
    assert resp.status_code == 200

    owner_user.tenant.refresh_from_db()
    assert owner_user.tenant.comm_auto_renew is True
    assert owner_user.tenant.comm_auto_renew_price_id == "price_credits_10_test"


@pytest.mark.django_db
def test_settings_patch_clears_price_id_when_disabling_auto_renewal(
    owner_user, settings
):
    settings.STRIPE_PRICE_CREDITS_10_ID = "price_credits_10_test"

    owner_user.tenant.comm_auto_renew = True
    owner_user.tenant.comm_auto_renew_price_id = "price_credits_10_test"
    owner_user.tenant.save(
        update_fields=["comm_auto_renew", "comm_auto_renew_price_id"]
    )

    c = APIClient()
    c.force_authenticate(user=owner_user)

    resp = c.patch(
        "/api/payments/stripe/settings/", {"auto_renewal": False}, format="json"
    )
    assert resp.status_code == 200

    owner_user.tenant.refresh_from_db()
    assert owner_user.tenant.comm_auto_renew is False
    assert owner_user.tenant.comm_auto_renew_price_id is None
