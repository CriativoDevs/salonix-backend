"""
Não havia nenhum sinal no Django Admin para identificar um tenant que se
cadastrou (ganhando acesso completo já no registo, ver
Tenant.objects.create em users/serializers.py) e nunca concluiu o
checkout — caso do JBarber em produção, só encontrado via investigação
manual no Stripe Dashboard e nos logs. `payment_status` fecha essa
lacuna de visibilidade.
"""

import pytest
from django.contrib import admin

from users.admin import _tenant_payment_status
from users.models import Tenant, UserFeatureFlags


@pytest.mark.django_db
class TestTenantPaymentStatusClassification:
    def test_promotional_billing_mode(self, tenant_fixture, user_fixture):
        tenant_fixture.billing_mode = Tenant.BILLING_MODE_PROMOTIONAL
        tenant_fixture.save(update_fields=["billing_mode"])

        assert _tenant_payment_status(tenant_fixture) == "promotional"

    def test_trialing_owner(self, tenant_fixture, user_fixture):
        ff = user_fixture.featureflags
        ff.pro_status = UserFeatureFlags.STATUS_TRIALING
        ff.save(update_fields=["pro_status"])

        assert _tenant_payment_status(tenant_fixture) == "trial"

    def test_active_paid_subscription(self, tenant_fixture, user_fixture):
        ff = user_fixture.featureflags
        ff.pro_status = UserFeatureFlags.STATUS_ACTIVE
        ff.save(update_fields=["pro_status"])

        assert _tenant_payment_status(tenant_fixture) == "paid"

    def test_checkout_started_but_not_completed(self, tenant_fixture, user_fixture):
        from payments.models import PaymentCustomer

        PaymentCustomer.objects.create(
            user=user_fixture, stripe_customer_id="cus_pending123"
        )

        assert _tenant_payment_status(tenant_fixture) == "pending"

    def test_checkout_never_started(self, tenant_fixture, user_fixture):
        assert _tenant_payment_status(tenant_fixture) == "never_started"


@pytest.mark.django_db
class TestTenantAdminPaymentStatusWiring:
    def test_payment_status_in_list_display(self):
        tenant_admin = admin.site._registry[Tenant]

        assert "payment_status" in tenant_admin.list_display

    def test_payment_status_filter_registered(self):
        tenant_admin = admin.site._registry[Tenant]
        filter_titles = [f.title for f in tenant_admin.list_filter if hasattr(f, "title")]

        assert "Status de pagamento" in filter_titles

    @pytest.mark.parametrize(
        "filter_value",
        ["paid", "trial", "pending", "never_started", "promotional"],
    )
    def test_changelist_loads_with_each_filter_value(
        self, admin_client, tenant_fixture, user_fixture, filter_value
    ):
        response = admin_client.get(
            "/admin/users/tenant/", {"payment_status": filter_value}
        )

        assert response.status_code == 200
