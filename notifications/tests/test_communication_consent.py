import pytest
from django.urls import reverse
from rest_framework.test import APIClient
from rest_framework import status

from users.models import Tenant, TenantStaffMember, CustomUser
from core.models import SalonCustomer, CustomerCommunicationConsent


@pytest.mark.django_db
class TestCommunicationConsent:
    def setup_method(self):
        self.client = APIClient()

    def _create_customer(self, tenant):
        return SalonCustomer.objects.create(tenant=tenant, name="Cliente Teste")

    def test_create_and_list(self, tenant_fixture, user_fixture):
        self.client.force_authenticate(user=user_fixture)
        customer = self._create_customer(tenant_fixture)

        url_create = reverse("communication-consent-create")
        payload = {
            "customer_id": customer.id,
            "channel": "email",
            "purpose": "marketing",
            "source": "admin",
        }
        r = self.client.post(url_create, payload)
        assert r.status_code == status.HTTP_201_CREATED
        data = r.json()
        assert data["status"] == "consented"
        assert data["consented_at"] is not None
        assert data["withdrawn_at"] is None

        url_list = reverse("communication-consent-list")
        r2 = self.client.get(url_list, {"customer_id": customer.id})
        assert r2.status_code == status.HTTP_200_OK
        items = r2.json()
        assert len(items) == 1
        assert items[0]["channel"] == "email"
        assert items[0]["purpose"] == "marketing"

    def test_withdraw_updates_existing(self, tenant_fixture, user_fixture):
        self.client.force_authenticate(user=user_fixture)
        customer = self._create_customer(tenant_fixture)

        CustomerCommunicationConsent.objects.create(
            tenant=tenant_fixture,
            customer=customer,
            channel="sms",
            purpose="transactional",
            status="consented",
        )

        url_withdraw = reverse("communication-consent-withdraw")
        payload = {
            "customer_id": customer.id,
            "channel": "sms",
            "purpose": "transactional",
            "source": "admin",
        }
        r = self.client.post(url_withdraw, payload)
        assert r.status_code == status.HTTP_200_OK
        data = r.json()
        assert data["status"] == "withdrawn"
        assert data["withdrawn_at"] is not None

    def test_unique_constraint_updates_not_duplicates(
        self, tenant_fixture, user_fixture
    ):
        self.client.force_authenticate(user=user_fixture)
        customer = self._create_customer(tenant_fixture)

        url_create = reverse("communication-consent-create")
        payload = {
            "customer_id": customer.id,
            "channel": "whatsapp",
            "purpose": "marketing",
            "source": "admin",
        }
        r1 = self.client.post(url_create, payload)
        assert r1.status_code == status.HTTP_201_CREATED
        r2 = self.client.post(url_create, payload)
        assert r2.status_code == status.HTTP_201_CREATED

        count = CustomerCommunicationConsent.objects.filter(
            tenant=tenant_fixture,
            customer=customer,
            channel="whatsapp",
            purpose="marketing",
        ).count()
        assert count == 1

    def test_isolated_by_tenant(self, tenant_fixture, user_fixture):
        other_tenant = Tenant.objects.create(slug="other", name="Other")
        other_user = CustomUser.objects.create_user(
            username="otheruser", email="o@example.com", password="x"
        )
        TenantStaffMember.objects.create(
            tenant=other_tenant,
            user=other_user,
            role=TenantStaffMember.Role.OWNER,
            status=TenantStaffMember.Status.ACTIVE,
        )

        customer_a = self._create_customer(tenant_fixture)
        customer_b = self._create_customer(other_tenant)

        CustomerCommunicationConsent.objects.create(
            tenant=tenant_fixture,
            customer=customer_a,
            channel="push",
            purpose="marketing",
            status="consented",
        )
        CustomerCommunicationConsent.objects.create(
            tenant=other_tenant,
            customer=customer_b,
            channel="push",
            purpose="marketing",
            status="consented",
        )

        self.client.force_authenticate(user=user_fixture)
        url_list = reverse("communication-consent-list")
        r = self.client.get(url_list)
        assert r.status_code == status.HTTP_200_OK
        items = r.json()
        assert len(items) == 1
