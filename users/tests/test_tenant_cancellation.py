from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase
from users.models import Tenant, CustomUser, TenantStaffMember
from django.utils import timezone


class TenantCancellationTest(APITestCase):
    def setUp(self):
        # Create Tenant
        self.tenant = Tenant.objects.create(
            name="Test Salon", slug="test-salon", plan_tier="standard", is_active=True
        )

        # Create Owner
        self.owner = CustomUser.objects.create_user(
            username="owner",
            email="owner@example.com",
            password="password123",
            tenant=self.tenant,
        )
        self.staff_owner = TenantStaffMember.objects.create(
            tenant=self.tenant, user=self.owner, role=TenantStaffMember.Role.OWNER
        )

        # Create Manager
        self.manager = CustomUser.objects.create_user(
            username="manager",
            email="manager@example.com",
            password="password123",
            tenant=self.tenant,
        )
        self.staff_manager = TenantStaffMember.objects.create(
            tenant=self.tenant, user=self.manager, role=TenantStaffMember.Role.MANAGER
        )

        self.url = reverse("me_tenant")

    def test_owner_can_cancel_tenant(self):
        self.client.force_authenticate(user=self.owner)
        response = self.client.delete(self.url)

        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)

        self.tenant.refresh_from_db()
        self.assertFalse(self.tenant.is_active)
        self.assertIsNotNone(self.tenant.deleted_at)

        # Verify data integrity (User still exists)
        self.assertTrue(CustomUser.objects.filter(pk=self.owner.pk).exists())
        self.assertTrue(
            TenantStaffMember.objects.filter(pk=self.staff_owner.pk).exists()
        )

    def test_manager_cannot_cancel_tenant(self):
        self.client.force_authenticate(user=self.manager)
        response = self.client.delete(self.url)

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

        self.tenant.refresh_from_db()
        self.assertTrue(self.tenant.is_active)
        self.assertIsNone(self.tenant.deleted_at)

    def test_idempotency_inactive_tenant(self):
        # Setup inactive tenant
        self.tenant.is_active = False
        self.tenant.deleted_at = timezone.now()
        self.tenant.save()

        original_deleted_at = self.tenant.deleted_at

        self.client.force_authenticate(user=self.owner)
        response = self.client.delete(self.url)

        # Middleware blocks access to inactive tenants with 403
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

        self.tenant.refresh_from_db()
        self.assertFalse(self.tenant.is_active)
        # Ensure deleted_at didn't change (service check)
        self.assertEqual(self.tenant.deleted_at, original_deleted_at)

    def test_inactive_tenant_cannot_access_api(self):
        # Setup inactive tenant
        self.tenant.is_active = False
        self.tenant.save()

        self.client.force_authenticate(user=self.owner)
        # Try to access MeTenantView (GET)
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
