import pytest
from users.models import CustomUser


@pytest.fixture
def user_fixture(db):
    return CustomUser.objects.create_user(
        username="testuser", email="test@example.com", password="testpass"
    )
