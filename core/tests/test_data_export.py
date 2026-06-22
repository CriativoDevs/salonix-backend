"""
BE-RGPD-01: exportacao de dados pessoais (Art. 15/20).

Endpoint sincrono que devolve os dados do tenant do owner como ficheiro JSON
(download). So o owner pode exportar; isolamento multi-tenant garantido.
"""

import json

from django.test.utils import override_settings
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from core.models import SalonCustomer
from users.models import CustomUser, Tenant, TenantStaffMember


class DataExportTest(APITestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(
            name="Export Salon",
            slug="export-salon",
            plan_tier="standard",
            is_active=True,
        )
        self.owner = CustomUser.objects.create_user(
            username="owner_exp",
            email="owner_exp@example.com",
            password="password123",
            tenant=self.tenant,
        )
        TenantStaffMember.objects.create(
            tenant=self.tenant, user=self.owner, role=TenantStaffMember.Role.OWNER
        )
        self.customer = SalonCustomer.objects.create(
            tenant=self.tenant,
            name="Maria Silva",
            email="maria.exp@example.com",
        )
        self.url = reverse("tenant-data-export")

    def test_owner_exports_own_data_as_json_download(self):
        self.client.force_authenticate(user=self.owner)
        resp = self.client.get(self.url)

        assert resp.status_code == status.HTTP_200_OK
        assert resp["Content-Type"].startswith("application/json")
        assert "attachment" in resp.get("Content-Disposition", "")

        payload = json.loads(resp.content)
        assert payload["metadata"]["tenant_slug"] == "export-salon"

        body = json.dumps(payload)
        # PII do cliente do tenant tem de constar da exportacao (Art. 15/20)
        assert "maria.exp@example.com" in body

    def test_manager_cannot_export(self):
        manager = CustomUser.objects.create_user(
            username="manager_exp",
            email="manager_exp@example.com",
            password="password123",
            tenant=self.tenant,
        )
        TenantStaffMember.objects.create(
            tenant=self.tenant, user=manager, role=TenantStaffMember.Role.MANAGER
        )
        self.client.force_authenticate(user=manager)
        resp = self.client.get(self.url)
        assert resp.status_code == status.HTTP_403_FORBIDDEN

    def test_export_excludes_other_tenant_data(self):
        other_tenant = Tenant.objects.create(
            name="Other Salon",
            slug="other-salon",
            plan_tier="standard",
            is_active=True,
        )
        SalonCustomer.objects.create(
            tenant=other_tenant, name="Outro Cliente", email="outro@example.com"
        )
        self.client.force_authenticate(user=self.owner)
        resp = self.client.get(self.url)

        assert resp.status_code == status.HTTP_200_OK
        body = resp.content.decode("utf-8")
        # Nunca expor dados de outro tenant
        assert "outro@example.com" not in body

    def test_unauthenticated_cannot_export(self):
        resp = self.client.get(self.url)
        assert resp.status_code in (
            status.HTTP_401_UNAUTHORIZED,
            status.HTTP_403_FORBIDDEN,
        )

    def test_export_is_rate_limited(self):
        from unittest import mock

        from rest_framework.throttling import ScopedRateThrottle

        self.client.force_authenticate(user=self.owner)
        # Cache isolado + rate baixo (patch direto no dict que o throttle le).
        with override_settings(
            CACHES={
                "default": {
                    "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
                    "LOCATION": "data-export-throttle",
                }
            }
        ), mock.patch.dict(
            ScopedRateThrottle.THROTTLE_RATES, {"data_export": "2/min"}
        ):
            assert self.client.get(self.url).status_code == status.HTTP_200_OK
            assert self.client.get(self.url).status_code == status.HTTP_200_OK
            assert (
                self.client.get(self.url).status_code
                == status.HTTP_429_TOO_MANY_REQUESTS
            )
