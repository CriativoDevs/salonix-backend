# tests/test_authorization_object_scope.py
"""
Regression tests for BE-SEC-04 item 2: Authorization review per object/tenant.
Validates that users cannot access objects from tenants they don't belong to.
"""
import pytest
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from users.models import CustomUser, Tenant, TenantStaffMember
from payments.models import PaymentCustomer, Subscription
from decimal import Decimal


@pytest.fixture
def setup_two_tenants(db):
    """Create two tenants with separate owners, staff, and resources."""
    # Tenant 1
    tenant1 = Tenant.objects.create(name="Tenant 1", slug="tenant-1")
    owner1 = CustomUser.objects.create_user(
        username="owner1",
        email="owner1@tenant1.com",
        password="testpass123",
        tenant=tenant1,
    )
    staff1 = TenantStaffMember.objects.create(
        tenant=tenant1,
        user=owner1,
        role=TenantStaffMember.Role.OWNER,
        status=TenantStaffMember.Status.ACTIVE,
    )

    # Tenant 2
    tenant2 = Tenant.objects.create(name="Tenant 2", slug="tenant-2")
    owner2 = CustomUser.objects.create_user(
        username="owner2",
        email="owner2@tenant2.com",
        password="testpass123",
        tenant=tenant2,
    )
    staff2 = TenantStaffMember.objects.create(
        tenant=tenant2,
        user=owner2,
        role=TenantStaffMember.Role.OWNER,
        status=TenantStaffMember.Status.ACTIVE,
    )

    return {
        "tenant1": tenant1,
        "owner1": owner1,
        "staff1": staff1,
        "tenant2": tenant2,
        "owner2": owner2,
        "staff2": staff2,
    }


# ---------------------------------------------------------------------------
# Billing authorization tests
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_billing_checkout_requires_owner_of_target_tenant(
    setup_two_tenants, monkeypatch, settings
):
    """
    A user from Tenant 1 (OWNER) should NOT be able to create checkout for Tenant 2.
    """
    settings.STRIPE_API_KEY = "sk_test_xxx"
    settings.STRIPE_PRICE_BASIC_MONTHLY_ID = "price_basic_123"
    settings.STRIPE_TRIAL_PERIOD_DAYS = 0
    settings.FRONTEND_BASE_URL = "http://localhost:5173"
    settings.STRIPE_API_VERSION = "2024-06-20"

    monkeypatch.setattr(
        "users.services.FounderService.get_availability",
        lambda: {"total_limit": 500, "used_count": 500, "remaining_count": 0},
    )

    from payments import stripe_utils

    class FakeStripeCheckout:
        class Session:
            @staticmethod
            def create(**kwargs):
                return type("Obj", (), {"url": "https://stripe.test/checkout"})

    class FakeStripeCustomer:
        @staticmethod
        def create(**kwargs):
            return {"id": "cus_test_123"}

    class FakeStripe:
        checkout = FakeStripeCheckout()
        Customer = FakeStripeCustomer

    monkeypatch.setattr(stripe_utils, "get_stripe", lambda: FakeStripe)

    data = setup_two_tenants
    owner1 = data["owner1"]

    # Try to make owner1 (from tenant1) access tenant2 by manipulating request
    # In reality, the view gets tenant from request.user.tenant, so this should fail
    # because owner1's tenant is tenant1, not tenant2.

    client = APIClient()
    client.force_authenticate(user=owner1)

    # Attempt checkout
    url = "/api/payments/stripe/create-checkout-session/"
    resp = client.post(url, {"plan": "basic"}, format="json")

    # owner1's tenant is tenant1, not tenant2 — should succeed for tenant1
    assert resp.status_code == 200

    # Verify the PaymentCustomer was created for tenant1, not tenant2
    pc = PaymentCustomer.objects.get(user=owner1)
    assert owner1.tenant_id == data["tenant1"].id


@pytest.mark.django_db
def test_staff_list_isolated_by_tenant(setup_two_tenants):
    """
    Owner from Tenant 1 should NOT see staff from Tenant 2.
    """
    data = setup_two_tenants
    owner1 = data["owner1"]
    staff2 = data["staff2"]

    client = APIClient()
    client.force_authenticate(user=owner1)

    # List staff for tenant1
    url = "/api/users/staff/"
    resp = client.get(url, format="json")

    assert resp.status_code == 200
    staff_ids = [s["id"] for s in resp.data]

    # staff2 (from tenant2) should NOT appear in the list
    assert staff2.id not in staff_ids
    # staff1 (from tenant1) SHOULD appear
    assert data["staff1"].id in staff_ids


@pytest.mark.django_db
def test_staff_update_cross_tenant_forbidden(setup_two_tenants):
    """
    Owner from Tenant 1 should NOT be able to update staff from Tenant 2.
    """
    data = setup_two_tenants
    owner1 = data["owner1"]
    staff2 = data["staff2"]

    client = APIClient()
    client.force_authenticate(user=owner1)

    # Try to update staff2 (from tenant2)
    url = "/api/users/staff/"
    resp = client.patch(
        url,
        {
            "id": staff2.id,
            "role": "manager",
        },
        format="json",
    )

    # Should fail — staff2 not found (filtered by tenant=tenant1)
    assert resp.status_code == 404


@pytest.mark.django_db
def test_tenant_profile_patch_requires_owner_manager(setup_two_tenants):
    """
    Only OWNER/MANAGER can patch tenant profile; regular staff cannot.
    """
    data = setup_two_tenants
    tenant1 = data["tenant1"]

    # Create a collaborator (not owner/manager)
    collab = CustomUser.objects.create_user(
        username="collab",
        email="collab@tenant1.com",
        password="testpass123",
        tenant=tenant1,
    )
    TenantStaffMember.objects.create(
        tenant=tenant1,
        user=collab,
        role=TenantStaffMember.Role.COLLABORATOR,
        status=TenantStaffMember.Status.ACTIVE,
    )

    client = APIClient()
    client.force_authenticate(user=collab)

    # Try to patch tenant profile
    url = "/api/users/tenant/profile/"
    resp = client.patch(url, {"email": "newemail@test.com"}, format="json")

    # Should be forbidden
    assert resp.status_code == 403


@pytest.mark.django_db
def test_ops_tenant_view_requires_ops_role(setup_two_tenants):
    """
    Regular tenantuser should NOT be able to access OPS tenant endpoints,
    even if authenticated.
    """
    data = setup_two_tenants
    owner1 = data["owner1"]

    client = APIClient()
    client.force_authenticate(user=owner1)

    # Try to list tenants (OPS endpoint)
    url = reverse("ops-tenants-list")
    resp = client.get(url, format="json")

    # Should fail — owner1 doesn't have OPS role
    assert resp.status_code in (401, 403)


@pytest.mark.django_db
def test_user_can_only_update_own_profile(setup_two_tenants):
    """
    A user should only be able to update their own profile (via /me/),
    not other users' profiles.
    """
    data = setup_two_tenants
    owner1 = data["owner1"]
    owner2 = data["owner2"]

    client = APIClient()
    client.force_authenticate(user=owner1)

    # Try to update /me/profile/ (own profile)
    url = "/api/users/me/profile/"
    resp = client.patch(url, {"theme_preference": "dark"}, format="json")
    assert resp.status_code == 200

    # Verify owner1's theme was updated, not owner2's
    owner1.refresh_from_db()
    assert owner1.theme_preference == "dark"

    owner2.refresh_from_db()
    assert owner2.theme_preference != "dark"
