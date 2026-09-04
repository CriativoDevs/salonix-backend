"""
BE-MARKETING-04 (#522): helper de elegibilidade para campanhas de email
marketing — reaproveita `CustomerCommunicationConsent` (purpose="marketing",
channel="email"), o mesmo modelo já usado pelo unsubscribe público.
"""

import pytest

from core.models import CustomerCommunicationConsent, SalonCustomer
from notifications.services import get_eligible_marketing_email_customers


@pytest.mark.django_db
class TestGetEligibleMarketingEmailCustomers:
    def test_excludes_customer_without_consent(self, tenant_fixture):
        SalonCustomer.objects.create(
            tenant=tenant_fixture, name="Sem Consentimento", email="a@example.com"
        )
        result = list(get_eligible_marketing_email_customers(tenant_fixture))
        assert result == []

    def test_includes_customer_with_active_consent(self, tenant_fixture):
        customer = SalonCustomer.objects.create(
            tenant=tenant_fixture, name="Com Consentimento", email="b@example.com"
        )
        CustomerCommunicationConsent.objects.create(
            tenant=tenant_fixture,
            customer=customer,
            channel="email",
            purpose="marketing",
            status="consented",
        )
        result = list(get_eligible_marketing_email_customers(tenant_fixture))
        assert result == [customer]

    def test_excludes_customer_with_withdrawn_consent(self, tenant_fixture):
        customer = SalonCustomer.objects.create(
            tenant=tenant_fixture, name="Unsubscribed", email="c@example.com"
        )
        CustomerCommunicationConsent.objects.create(
            tenant=tenant_fixture,
            customer=customer,
            channel="email",
            purpose="marketing",
            status="withdrawn",
        )
        result = list(get_eligible_marketing_email_customers(tenant_fixture))
        assert result == []

    def test_excludes_customer_without_email_even_with_consent(self, tenant_fixture):
        customer = SalonCustomer.objects.create(
            tenant=tenant_fixture, name="Sem Email", email=""
        )
        CustomerCommunicationConsent.objects.create(
            tenant=tenant_fixture,
            customer=customer,
            channel="email",
            purpose="marketing",
            status="consented",
        )
        result = list(get_eligible_marketing_email_customers(tenant_fixture))
        assert result == []

    def test_excludes_consent_from_other_channel(self, tenant_fixture):
        """Consentimento de SMS/marketing não habilita email/marketing."""
        customer = SalonCustomer.objects.create(
            tenant=tenant_fixture, name="Consent SMS", email="d@example.com"
        )
        CustomerCommunicationConsent.objects.create(
            tenant=tenant_fixture,
            customer=customer,
            channel="sms",
            purpose="marketing",
            status="consented",
        )
        result = list(get_eligible_marketing_email_customers(tenant_fixture))
        assert result == []

    def test_scoped_by_tenant(self, tenant_fixture):
        from users.models import Tenant

        other_tenant = Tenant.objects.create(slug="other-tenant", name="Other Tenant")
        other_customer = SalonCustomer.objects.create(
            tenant=other_tenant, name="Outro Tenant", email="e@example.com"
        )
        CustomerCommunicationConsent.objects.create(
            tenant=other_tenant,
            customer=other_customer,
            channel="email",
            purpose="marketing",
            status="consented",
        )
        result = list(get_eligible_marketing_email_customers(tenant_fixture))
        assert result == []
