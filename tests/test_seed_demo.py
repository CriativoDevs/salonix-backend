import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import override_settings

from core.models import Appointment, SalonCustomer


User = get_user_model()


@pytest.mark.django_db
def test_seed_demo_uses_configurable_password():
    custom_password = "Test@123"
    with override_settings(SMOKE_USER_PASSWORD=custom_password):
        call_command("seed_demo")

    pro = User.objects.get(username="pro_smoke")
    client = User.objects.get(username="client_smoke")

    assert pro.check_password(custom_password)
    assert client.check_password(custom_password)

    customers = SalonCustomer.objects.filter(tenant__slug="default")
    assert customers.exists()
    assert Appointment.objects.filter(customer__isnull=False).count() > 0
