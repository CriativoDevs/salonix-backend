import pytest
from core.models import Service
from users.models import CustomUser


@pytest.mark.django_db
def test_create_service():
    user = CustomUser.objects.create_user(
        username="testuser", email="test@example.com", password="123456"
    )

    service = Service.objects.create(
        user=user,
        name="Corte de Cabelo",
        price_eur=15.00,
        duration_minutes=30,
    )

    assert service.name == "Corte de Cabelo"
    assert service.price_eur == 15.00
    assert service.duration_minutes == 30
    assert service.user == user
