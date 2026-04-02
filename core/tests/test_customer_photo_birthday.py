from io import BytesIO

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from PIL import Image
from rest_framework import status
from rest_framework.test import APIClient

from core.models import SalonCustomer
from core.views import _create_client_jwt_tokens
from users.models import CustomUser, Tenant, TenantStaffMember


@pytest.fixture(autouse=True)
def _disable_whitenoise(settings):
    settings.MIDDLEWARE = [
        middleware
        for middleware in settings.MIDDLEWARE
        if "whitenoise" not in middleware.lower()
    ]


def _make_test_image(name="customer.png", size=(80, 80), color=(200, 80, 40)):
    buffer = BytesIO()
    image = Image.new("RGB", size, color)
    image.save(buffer, format="PNG")
    return SimpleUploadedFile(name, buffer.getvalue(), content_type="image/png")


@pytest.mark.django_db
def test_staff_can_create_customer_with_photo_and_birthday(tenant_fixture):
    owner = CustomUser.objects.create_user(
        username="owner-customer-photo",
        email="owner-customer-photo@example.com",
        password="StrongPass123",
        tenant=tenant_fixture,
    )
    TenantStaffMember.objects.create(
        tenant=tenant_fixture,
        user=owner,
        role=TenantStaffMember.Role.OWNER,
        status=TenantStaffMember.Status.ACTIVE,
    )

    client = APIClient()
    client.force_authenticate(user=owner)

    response = client.post(
        reverse("salon-customers-list"),
        {
            "name": "Cliente com Foto",
            "email": "cliente-foto@example.com",
            "birthday": "1988-11-05",
            "photo": _make_test_image(),
        },
        format="multipart",
    )

    assert response.status_code == status.HTTP_201_CREATED
    customer = SalonCustomer.objects.get(email="cliente-foto@example.com")
    assert str(customer.birthday) == "1988-11-05"
    assert customer.photo.name.startswith("customer_photos/")
    assert response.data["birthday"] == "1988-11-05"
    assert "customer_photos/" in response.data["photo"]


@pytest.mark.django_db
def test_client_can_patch_own_profile_photo_and_birthday():
    tenant = Tenant.objects.create(
        name="Client Profile Tenant",
        slug="client-profile-tenant",
        plan_tier=Tenant.PLAN_BASIC,
        pwa_client_enabled=True,
    )
    customer = SalonCustomer.objects.create(
        tenant=tenant,
        name="Cliente Perfil",
        email="cliente-perfil@example.com",
        is_active=True,
    )
    customer.set_password("ClientPass123")
    customer.save(update_fields=["password"])

    tokens = _create_client_jwt_tokens(tenant, customer)
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {tokens['access']}")

    response = client.patch(
        reverse("clients_me_profile"),
        {
            "birthday": "1995-01-27",
            "photo": _make_test_image(name="client-self.png"),
        },
        format="multipart",
    )

    assert response.status_code == status.HTTP_200_OK
    customer.refresh_from_db()
    assert str(customer.birthday) == "1995-01-27"
    assert customer.photo.name.startswith("customer_photos/")
    assert response.data["birthday"] == "1995-01-27"
    assert "customer_photos/" in response.data["photo"]
