import pytest

pytestmark = pytest.mark.django_db


def test_payment_customer_admin_changeform_loads(admin_client, django_user_model):
    """Regressão: PaymentCustomerAdmin quebrava com FieldError porque
    `tenant_name` (método do admin, usado em list_display/fieldsets) não
    estava declarado em `readonly_fields`.
    """
    from payments.models import PaymentCustomer
    from users.models import Tenant

    tenant = Tenant.objects.create(name="Admin Test Tenant", slug="admin-test-tenant")
    user = django_user_model.objects.create_user(
        username="pc_admin_test", email="pc_admin_test@example.com", tenant=tenant
    )
    pc = PaymentCustomer.objects.create(user=user, stripe_customer_id="cus_test123")

    response = admin_client.get(f"/admin/payments/paymentcustomer/{pc.pk}/change/")

    assert response.status_code == 200
