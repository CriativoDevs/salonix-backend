import pytest
from django.urls import reverse
from django.test import override_settings
from prometheus_client import Counter, CollectorRegistry
from rest_framework import status
from rest_framework.test import APIClient

from users.models import CustomUser, Tenant, TenantStaffMember


@pytest.mark.django_db
@override_settings(FRONTEND_BASE_URL="http://localhost:5173")
def test_invite_sends_email_and_metrics(monkeypatch):
    registry = CollectorRegistry()
    fake_counter = Counter(
        "users_staff_invite_events_total",
        "",
        ("event", "result"),
        registry=registry,
    )

    # Patch counter and email sender used inside the view
    monkeypatch.setattr(
        "users.views.USERS_STAFF_INVITE_EVENTS_TOTAL", fake_counter, raising=True
    )
    monkeypatch.setattr(
        "users.views.send_staff_invite_email",
        lambda to_email, accept_url, salon_name, inviter_name: True,
        raising=True,
    )

    tenant = Tenant.objects.create(name="Salon Test", slug="salon-test")
    owner = CustomUser.objects.create_user(
        username="owner",
        email="owner@test.local",
        password="pass12345",
        tenant=tenant,
    )
    TenantStaffMember.objects.create(
        tenant=tenant,
        user=owner,
        role=TenantStaffMember.Role.OWNER,
        status=TenantStaffMember.Status.ACTIVE,
    )

    client = APIClient()
    client.force_authenticate(user=owner)
    url = reverse("tenant_staff")
    payload = {"email": "collab@test.local", "role": TenantStaffMember.Role.COLLABORATOR}
    response = client.post(url, payload, format="json")

    assert response.status_code == status.HTTP_201_CREATED
    data = response.data
    assert "invite_token" in data and isinstance(data["invite_token"], str)
    assert data.get("status") == TenantStaffMember.Status.INVITED

    # Assert counter increment for success invite
    samples = fake_counter.collect()[0].samples
    invite_success = [
        s for s in samples if s.labels.get("event") == "invite" and s.labels.get("result") == "success"
    ]
    assert invite_success and invite_success[0].value == 1


@pytest.mark.django_db
def test_accept_invite_increments_metrics(monkeypatch):
    registry = CollectorRegistry()
    fake_counter = Counter(
        "users_staff_invite_events_total",
        "",
        ("event", "result"),
        registry=registry,
    )

    monkeypatch.setattr(
        "users.views.USERS_STAFF_INVITE_EVENTS_TOTAL", fake_counter, raising=True
    )

    tenant = Tenant.objects.create(name="Salon Accept", slug="salon-accept")
    owner = CustomUser.objects.create_user(
        username="owner2",
        email="owner2@test.local",
        password="pass12345",
        tenant=tenant,
    )
    TenantStaffMember.objects.create(
        tenant=tenant,
        user=owner,
        role=TenantStaffMember.Role.OWNER,
        status=TenantStaffMember.Status.ACTIVE,
    )

    collab = CustomUser.objects.create_user(
        username="collab",
        email="collab@test.local",
        password="pass12345",
        tenant=tenant,
    )
    staff = TenantStaffMember.objects.create(
        tenant=tenant,
        user=collab,
        role=TenantStaffMember.Role.COLLABORATOR,
        status=TenantStaffMember.Status.INVITED,
    )
    staff.set_invite(token="tok-accept-1", expires_at=None, invited_by=owner)

    client = APIClient()
    url = reverse("tenant_staff_accept")
    payload = {"token": "tok-accept-1", "password": "StrongPass!9"}
    response = client.post(url, payload, format="json")

    assert response.status_code == status.HTTP_200_OK
    data = response.data
    assert data.get("status") == TenantStaffMember.Status.ACTIVE

    # Assert counter increment for accept success
    samples = fake_counter.collect()[0].samples
    accept_success = [
        s for s in samples if s.labels.get("event") == "accept" and s.labels.get("result") == "success"
    ]
    assert accept_success and accept_success[0].value == 1

