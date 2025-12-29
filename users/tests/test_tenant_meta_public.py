import pytest
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient
from users.models import Tenant

@pytest.mark.django_db
class TestTenantMetaPublic:
    def setup_method(self):
        self.client = APIClient()
        self.url = "/api/users/tenant/meta/"
        self.tenant = Tenant.objects.create(
            name="Test Tenant",
            slug="test-tenant",
            plan_tier="scale",
            is_active=True
        )

    def test_get_tenant_meta_public_access(self):
        """Verify endpoint is public and accessible via query param"""
        response = self.client.get(f"{self.url}?tenant={self.tenant.slug}")
        assert response.status_code == status.HTTP_200_OK
        
        data = response.data
        # Verify required fields
        assert data["name"] == self.tenant.name
        assert data["slug"] == self.tenant.slug
        
        # Verify branding fields (flat structure in TenantMetaSerializer)
        assert "logo_url" in data
        assert "favicon_url" in data
        assert "app_name" in data
        
        # Verify feature flags
        assert "feature_flags" in data
        assert isinstance(data["feature_flags"], dict)

    def test_get_tenant_meta_via_header(self):
        """Verify endpoint accepts X-Tenant-Slug header"""
        response = self.client.get(
            self.url, 
            headers={"X-Tenant-Slug": self.tenant.slug}
        )
        assert response.status_code == status.HTTP_200_OK
        assert response.data["slug"] == self.tenant.slug

    def test_get_tenant_meta_not_found(self):
        """Verify behavior for non-existent tenant"""
        # Current implementation returns 400 Bad Request for TenantError
        response = self.client.get(f"{self.url}?tenant=nonexistent12345")
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "não encontrado" in str(response.data)

    def test_security_sensitive_data(self):
        """Verify sensitive data is NOT exposed"""
        response = self.client.get(f"{self.url}?tenant={self.tenant.slug}")
        data = response.data
        
        assert "users" not in data
        assert "billing" not in data
