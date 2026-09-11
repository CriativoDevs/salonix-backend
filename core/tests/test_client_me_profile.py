import io

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from PIL import Image
from rest_framework import status
from rest_framework.test import APIClient

from users.models import Tenant
from core.models import SalonCustomer


def _make_image_file(name="avatar.png", size=(200, 200)):
    buffer = io.BytesIO()
    Image.new("RGB", size, (120, 160, 200)).save(buffer, format="PNG")
    return SimpleUploadedFile(name, buffer.getvalue(), content_type="image/png")


@pytest.mark.django_db
class TestClientsMeProfileView:
    def setup_method(self):
        self.tenant = Tenant.objects.create(
            name="Test Salon",
            slug="test-salon-profile",
            plan_tier=Tenant.PLAN_BASIC,
            pwa_client_enabled=True,
        )
        self.customer = SalonCustomer.objects.create(
            tenant=self.tenant,
            name="Test Client",
            email="client-profile@test.com",
            phone_number="+351911111111",
            notes="Nota interna do staff sobre o cliente.",
            is_active=True,
        )
        self.customer.set_password("securepass123")
        self.customer.save()

        self.client = APIClient()
        login_response = self.client.post(
            reverse("clients_login"),
            {
                "email": "client-profile@test.com",
                "password": "securepass123",
                "tenant_slug": self.tenant.slug,
            },
            format="json",
        )
        assert login_response.status_code == status.HTTP_200_OK
        self.access_token = login_response.data["access"]
        self.url = "/api/clients/me/profile/"

    def _auth_headers(self):
        return {"HTTP_AUTHORIZATION": f"Bearer {self.access_token}"}

    def test_get_profile_does_not_expose_notes(self):
        response = self.client.get(self.url, **self._auth_headers())

        assert response.status_code == status.HTTP_200_OK
        assert "notes" not in response.data
        assert response.data["name"] == "Test Client"

    def test_patch_notes_is_ignored(self):
        response = self.client.patch(
            self.url,
            {"notes": "Tentativa do cliente de sobrescrever a nota do staff."},
            format="json",
            **self._auth_headers(),
        )

        assert response.status_code == status.HTTP_200_OK
        assert "notes" not in response.data

        self.customer.refresh_from_db()
        assert self.customer.notes == "Nota interna do staff sobre o cliente."

    def test_patch_allowed_fields_still_works(self):
        response = self.client.patch(
            self.url,
            {"name": "Nome Atualizado"},
            format="json",
            **self._auth_headers(),
        )

        assert response.status_code == status.HTTP_200_OK
        assert response.data["name"] == "Nome Atualizado"

        self.customer.refresh_from_db()
        assert self.customer.name == "Nome Atualizado"

    def test_client_can_upload_own_photo(self):
        response = self.client.patch(
            self.url,
            {"photo": _make_image_file()},
            format="multipart",
            **self._auth_headers(),
        )

        assert response.status_code == status.HTTP_200_OK

        self.customer.refresh_from_db()
        assert self.customer.photo
        assert "customer_photos/" in self.customer.photo.name

    def test_photo_is_returned_as_absolute_url(self):
        self.client.patch(
            self.url,
            {"photo": _make_image_file()},
            format="multipart",
            **self._auth_headers(),
        )

        response = self.client.get(self.url, **self._auth_headers())

        assert response.status_code == status.HTTP_200_OK
        assert response.data["photo"].startswith("http://")

    def test_photo_too_small_is_rejected(self):
        response = self.client.patch(
            self.url,
            {"photo": _make_image_file(size=(20, 20))},
            format="multipart",
            **self._auth_headers(),
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST

        self.customer.refresh_from_db()
        assert not self.customer.photo
