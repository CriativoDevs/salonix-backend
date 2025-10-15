import pytest
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient
from unittest.mock import patch

from users.models import Tenant, CustomUser
from core.models import SalonCustomer


@pytest.mark.django_db
def test_resend_invite_success():
    tenant = Tenant.objects.create(
        name="Invite Salon",
        slug="invite-salon",
        plan_tier=Tenant.PLAN_STANDARD,
        pwa_client_enabled=True,
    )
    user = CustomUser.objects.create_user(
        username="owner",
        email="owner@invite.com",
        password="testpass123",
        tenant=tenant,
    )
    customer = SalonCustomer.objects.create(
        tenant=tenant,
        name="Cliente",
        email="cliente@example.com",
    )

    client = APIClient()
    client.force_authenticate(user=user)

    with patch("core.views.send_customer_pwa_invite", return_value=True) as mocked:
        url = reverse("salon-customers-invite", args=[customer.id])
        response = client.post(url)

    assert response.status_code == status.HTTP_202_ACCEPTED
    assert response.json()["status"] == "queued"
    mocked.assert_called_once()


@pytest.mark.django_db
def test_resend_invite_requires_pwa_enabled():
    tenant = Tenant.objects.create(
        name="Basic",
        slug="basic",
        plan_tier=Tenant.PLAN_BASIC,
        pwa_client_enabled=False,
    )
    user = CustomUser.objects.create_user(
        username="basic-owner",
        email="basic@example.com",
        password="testpass123",
        tenant=tenant,
    )
    customer = SalonCustomer.objects.create(
        tenant=tenant,
        name="Cliente",
        email="cliente@example.com",
    )

    client = APIClient()
    client.force_authenticate(user=user)
    url = reverse("salon-customers-invite", args=[customer.id])
    response = client.post(url)

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert "PWA" in response.data["detail"]


@pytest.mark.django_db
def test_resend_invite_requires_email():
    tenant = Tenant.objects.create(
        name="Invite",
        slug="invite",
        plan_tier=Tenant.PLAN_STANDARD,
        pwa_client_enabled=True,
    )
    user = CustomUser.objects.create_user(
        username="owner2",
        email="owner2@invite.com",
        password="testpass123",
        tenant=tenant,
    )
    customer = SalonCustomer.objects.create(
        tenant=tenant,
        name="Sem Email",
        email="",
    )

    client = APIClient()
    client.force_authenticate(user=user)
    url = reverse("salon-customers-invite", args=[customer.id])
    response = client.post(url)

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert "e-mail" in response.data["detail"].lower()


@pytest.mark.django_db
def test_auto_invite_triggered_on_create():
    tenant = Tenant.objects.create(
        name="Auto",
        slug="auto",
        plan_tier=Tenant.PLAN_STANDARD,
        pwa_client_enabled=True,
        auto_invite_enabled=True,
    )
    user = CustomUser.objects.create_user(
        username="owner-auto",
        email="owner@auto.com",
        password="testpass123",
        tenant=tenant,
    )

    client = APIClient()
    client.force_authenticate(user=user)

    with patch("core.views.send_customer_pwa_invite", return_value=True) as mocked:
        response = client.post(
            reverse("salon-customers-list"),
            {
                "name": "Cliente Auto",
                "email": "cliente.auto@exemplo.com",
            },
            format="json",
        )

    assert response.status_code == status.HTTP_201_CREATED
    mocked.assert_called_once()


@pytest.mark.django_db
def test_auto_invite_not_triggered_without_email():
    tenant = Tenant.objects.create(
        name="Auto",
        slug="auto-no-email",
        plan_tier=Tenant.PLAN_STANDARD,
        pwa_client_enabled=True,
        auto_invite_enabled=True,
    )
    user = CustomUser.objects.create_user(
        username="owner-auto2",
        email="owner2@auto.com",
        password="testpass123",
        tenant=tenant,
    )

    client = APIClient()
    client.force_authenticate(user=user)

    with patch("core.views.send_customer_pwa_invite") as mocked:
        response = client.post(
            reverse("salon-customers-list"),
            {
                "name": "Sem Email",
                "email": "",
                "phone_number": "+351999000111",
            },
            format="json",
        )

    assert response.status_code == status.HTTP_201_CREATED
    mocked.assert_not_called()
