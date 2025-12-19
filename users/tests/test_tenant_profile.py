import pytest
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from users.models import Tenant, CustomUser, TenantStaffMember


@pytest.mark.django_db
class TestTenantProfileEndpoint:
    def setup_method(self):
        self.client = APIClient()

    def _create_tenant_with_owner(self, *, contact_email=None, contact_phone=None):
        tenant = Tenant.objects.create(
            name="Profile Salon",
            slug="profile-salon",
            contact_email=contact_email,
            contact_phone=contact_phone,
            is_active=True,
        )
        owner = CustomUser.objects.create_user(
            username="owner",
            email="owner@example.com",
            password="Owner123!",
            tenant=tenant,
        )
        TenantStaffMember.objects.create(
            tenant=tenant,
            user=owner,
            role=TenantStaffMember.Role.OWNER,
            status=TenantStaffMember.Status.ACTIVE,
        )
        return tenant, owner

    def test_get_profile_with_query_param_and_owner_fallback(self):
        tenant, _owner = self._create_tenant_with_owner(
            contact_email=None, contact_phone="+351911111111"
        )

        url = reverse("tenant_profile")
        resp = self.client.get(url, {"tenant": tenant.slug})

        assert resp.status_code == status.HTTP_200_OK
        data = resp.data["profile"]
        assert data["phone"] == "+351911111111"
        # Sem contact_email, deve cair no e-mail do owner
        assert data["email"] == "owner@example.com"

    def test_get_profile_with_header(self):
        tenant, _owner = self._create_tenant_with_owner(
            contact_email="salon@example.com", contact_phone=None
        )

        url = reverse("tenant_profile")
        resp = self.client.get(url, HTTP_X_TENANT_SLUG=tenant.slug)

        assert resp.status_code == status.HTTP_200_OK
        data = resp.data["profile"]
        assert data["email"] == "salon@example.com"
        assert data["phone"] is None

    def test_get_profile_missing_param_returns_400(self):
        url = reverse("tenant_profile")
        resp = self.client.get(url)
        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert "error" in resp.data

    def test_patch_requires_auth(self):
        tenant, _owner = self._create_tenant_with_owner(
            contact_email="old@example.com", contact_phone="+351900000000"
        )

        url = reverse("tenant_profile")
        resp = self.client.patch(
            url,
            {"profile": {"email": "new@example.com", "phone": "+351912345678"}},
            format="json",
        )
        assert resp.status_code == status.HTTP_401_UNAUTHORIZED

    def test_patch_denied_for_collaborator(self):
        tenant, owner = self._create_tenant_with_owner(
            contact_email="old@example.com", contact_phone="+351900000000"
        )
        # Criar colaborador associado ao mesmo tenant
        collab = CustomUser.objects.create_user(
            username="collab",
            email="collab@example.com",
            password="Collab123!",
            tenant=tenant,
        )
        TenantStaffMember.objects.create(
            tenant=tenant,
            user=collab,
            role=TenantStaffMember.Role.COLLABORATOR,
            status=TenantStaffMember.Status.ACTIVE,
        )

        # Autenticar como colaborador
        self.client.force_authenticate(user=collab)
        url = reverse("tenant_profile")
        resp = self.client.patch(
            url, {"profile": {"email": "new@example.com"}}, format="json"
        )
        assert resp.status_code == status.HTTP_403_FORBIDDEN

        # Sanity: como owner deve permitir
        self.client.force_authenticate(user=owner)
        resp2 = self.client.patch(
            url, {"profile": {"email": "new@example.com", "phone": ""}}, format="json"
        )
        assert resp2.status_code == status.HTTP_200_OK
        data = resp2.data["profile"]
        assert data["email"] == "new@example.com"
        # Phone vazio deve resultar em None
        assert data["phone"] is None
