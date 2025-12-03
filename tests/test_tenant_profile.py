import pytest
from django.test import TestCase
from rest_framework.test import APIClient
from django.contrib.auth import get_user_model

from users.models import Tenant, TenantStaffMember


class TenantProfileTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        User = get_user_model()

        self.tenant = Tenant.objects.create(name="Salon X", slug="salonx")

        # Owner
        self.owner = User.objects.create_user(
            username="owner",
            email="owner@salonx.test",
            password="pass12345",
            tenant=self.tenant,
        )
        TenantStaffMember.objects.create(
            tenant=self.tenant,
            user=self.owner,
            role=TenantStaffMember.Role.OWNER,
        )

        # Collaborator
        self.collab = User.objects.create_user(
            username="collab",
            email="collab@salonx.test",
            password="pass12345",
            tenant=self.tenant,
        )
        TenantStaffMember.objects.create(
            tenant=self.tenant,
            user=self.collab,
            role=TenantStaffMember.Role.COLLABORATOR,
        )

    def test_meta_includes_profile_with_owner_email_fallback(self):
        resp = self.client.get(
            "/api/users/tenant/meta/",
            {"tenant": self.tenant.slug},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "profile" in data
        assert data["profile"]["email"] == "owner@salonx.test"

    def test_profile_get_uses_fallback_when_contact_empty(self):
        resp = self.client.get(
            "/api/users/tenant/profile/",
            {"tenant": self.tenant.slug},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["profile"]["email"] == "owner@salonx.test"

    def test_profile_patch_requires_owner_or_manager(self):
        # Collaborator should not be allowed
        self.client.force_authenticate(user=self.collab)
        resp = self.client.patch(
            "/api/users/tenant/profile/",
            {"email": "public@salonx.test", "phone": "+351912345678"},
            format="json",
        )
        assert resp.status_code == 403

        # Owner can update
        self.client.force_authenticate(user=self.owner)
        resp2 = self.client.patch(
            "/api/users/tenant/profile/",
            {"email": "public@salonx.test", "phone": "+351912345678"},
            format="json",
        )
        assert resp2.status_code == 200
        payload = resp2.json()["profile"]
        assert payload["email"] == "public@salonx.test"
        assert payload["phone"].startswith("+351")

