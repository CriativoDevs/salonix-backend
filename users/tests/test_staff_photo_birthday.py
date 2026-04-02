from io import BytesIO

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from PIL import Image
from rest_framework import status
from rest_framework.test import APIClient

from users.models import CustomUser, TenantStaffMember


@pytest.fixture(autouse=True)
def _disable_whitenoise(settings):
    settings.MIDDLEWARE = [
        middleware
        for middleware in settings.MIDDLEWARE
        if "whitenoise" not in middleware.lower()
    ]


def _make_test_image(name="avatar.png", size=(80, 80), color=(10, 120, 200)):
    buffer = BytesIO()
    image = Image.new("RGB", size, color)
    image.save(buffer, format="PNG")
    return SimpleUploadedFile(name, buffer.getvalue(), content_type="image/png")


@pytest.mark.django_db
def test_me_profile_patch_updates_photo_and_birthday(tenant_fixture):
    user = CustomUser.objects.create_user(
        username="profile-photo",
        email="profile-photo@example.com",
        password="StrongPass123",
        tenant=tenant_fixture,
    )

    client = APIClient()
    client.force_authenticate(user=user)

    response = client.patch(
        reverse("me_profile"),
        {
            "birthday": "1992-07-18",
            "photo": _make_test_image(),
        },
        format="multipart",
    )

    assert response.status_code == status.HTTP_200_OK
    user.refresh_from_db()
    assert str(user.birthday) == "1992-07-18"
    assert user.photo.name.startswith("staff_photos/")
    assert response.data["birthday"] == "1992-07-18"
    assert "staff_photos/" in response.data["photo"]


@pytest.mark.django_db
def test_staff_contact_patch_updates_photo_and_birthday_without_email(tenant_fixture):
    owner = CustomUser.objects.create_user(
        username="owner-staff-photo",
        email="owner-staff-photo@example.com",
        password="StrongPass123",
        tenant=tenant_fixture,
    )
    TenantStaffMember.objects.create(
        tenant=tenant_fixture,
        user=owner,
        role=TenantStaffMember.Role.OWNER,
        status=TenantStaffMember.Status.ACTIVE,
    )

    collaborator = CustomUser.objects.create_user(
        username="collab-staff-photo",
        email="collab-staff-photo@example.com",
        password="StrongPass123",
        tenant=tenant_fixture,
    )
    staff_member = TenantStaffMember.objects.create(
        tenant=tenant_fixture,
        user=collaborator,
        role=TenantStaffMember.Role.COLLABORATOR,
        status=TenantStaffMember.Status.ACTIVE,
    )

    client = APIClient()
    client.force_authenticate(user=owner)

    response = client.patch(
        reverse("tenant_staff_contact_update"),
        {
            "id": staff_member.id,
            "birthday": "1990-03-09",
            "photo": _make_test_image(name="staff-contact.png"),
        },
        format="multipart",
    )

    assert response.status_code == status.HTTP_200_OK
    collaborator.refresh_from_db()
    assert str(collaborator.birthday) == "1990-03-09"
    assert collaborator.photo.name.startswith("staff_photos/")
    assert response.data["birthday"] == "1990-03-09"
    assert "staff_photos/" in response.data["photo"]
