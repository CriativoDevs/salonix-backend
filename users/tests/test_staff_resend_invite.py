from unittest.mock import patch, MagicMock
import pytest
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from users.models import CustomUser, Tenant, TenantStaffMember


@pytest.mark.django_db
def test_resend_invite_requires_member_id():
    tenant = Tenant.objects.create(name="Salon", slug="salon")
    owner = CustomUser.objects.create_user(
        username="owner",
        email="owner@salon.local",
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
    url = reverse("tenant_staff_resend")
    response = client.post(url, {}, format="json")
    assert response.status_code == status.HTTP_400_BAD_REQUEST
    # Erro segue formato estruturado
    details = (response.data.get("error") or {}).get("details") or {}
    assert "id" in details


@pytest.mark.django_db
def test_resend_invite_fails_without_email():
    tenant = Tenant.objects.create(name="Salon", slug="salon")
    owner = CustomUser.objects.create_user(
        username="owner2",
        email="owner2@salon.local",
        password="pass12345",
        tenant=tenant,
    )
    TenantStaffMember.objects.create(
        tenant=tenant,
        user=owner,
        role=TenantStaffMember.Role.OWNER,
        status=TenantStaffMember.Status.ACTIVE,
    )

    # Colaborador sem e-mail
    collab = CustomUser.objects.create_user(
        username="collab",
        email="tmp@salon.local",
        password="pass12345",
        tenant=tenant,
    )
    collab.email = ""
    collab.save(update_fields=["email"])
    staff = TenantStaffMember.objects.create(
        tenant=tenant,
        user=collab,
        role=TenantStaffMember.Role.COLLABORATOR,
        status=TenantStaffMember.Status.INVITED,
    )

    client = APIClient()
    client.force_authenticate(user=owner)
    url = reverse("tenant_staff_resend")
    response = client.post(url, {"id": staff.id}, format="json")
    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert (
        "e-mail" in response.data.get("detail", "").lower()
        or "email" in response.data.get("detail", "").lower()
    )


@pytest.mark.django_db
def test_resend_invite_generates_new_token(monkeypatch):
    tenant = Tenant.objects.create(name="Salon", slug="salon")
    owner = CustomUser.objects.create_user(
        username="owner3",
        email="owner3@salon.local",
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
        username="collab2",
        email="collab2@salon.local",
        password="pass12345",
        tenant=tenant,
    )
    staff = TenantStaffMember.objects.create(
        tenant=tenant,
        user=collab,
        role=TenantStaffMember.Role.COLLABORATOR,
        status=TenantStaffMember.Status.INVITED,
    )
    staff.set_invite(token="tok-old", expires_at=None, invited_by=owner)

    # Evitar envio real de e-mail
    monkeypatch.setattr(
        "users.views.send_staff_invite_email",
        lambda to_email, accept_url, salon_name, inviter_name: True,
        raising=True,
    )

    client = APIClient()
    client.force_authenticate(user=owner)
    url = reverse("tenant_staff_resend")
    response = client.post(url, {"id": staff.id}, format="json")
    assert response.status_code == status.HTTP_200_OK

    assert response.data.get("invite_token") != "tok-old"
    assert response.data.get("status") == TenantStaffMember.Status.INVITED
