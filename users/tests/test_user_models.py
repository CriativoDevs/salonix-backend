import pytest
from django.contrib.auth import get_user_model
from django.db.utils import IntegrityError
from django.core.exceptions import ValidationError
from typing import Any, cast

User = get_user_model()


@pytest.mark.django_db
class TestCustomUserModel:

    def test_create_regular_user(self):
        user = User.objects.create_user(
            username="testuser", email="test@example.com", password="testpass123"
        )
        assert user.username == "testuser"
        assert user.email == "test@example.com"
        assert user.is_active is True
        assert user.is_staff is False
        assert user.is_superuser is False

    def test_create_superuser(self):
        admin = User.objects.create_superuser(
            username="adminuser", email="admin@example.com", password="adminpass123"
        )
        assert admin.is_staff is True
        assert admin.is_superuser is True
        assert admin.is_active is True

    def test_user_str_representation(self):
        user = User.objects.create_user(
            username="myuser", email="myuser@example.com", password="securepass"
        )
        # Com multi-tenant, o str agora inclui o nome do tenant
        assert str(user) == "myuser (Test Default Salon)"

    def test_user_without_email_should_fail(self):
        with pytest.raises(ValueError):
            User.objects.create_user(
                username="noemail", email=cast(Any, None), password="testpass"
            )

    def test_user_without_username_should_fail(self):
        with pytest.raises(ValueError):
            User.objects.create_user(
                username=cast(Any, None), email="x@x.com", password="testpass"
            )

    def test_duplicate_email_raises_integrity_error(self):
        User.objects.create_user(
            username="first",
            email="duplicate@example.com",
            password="StrongPass123",
        )

        with pytest.raises(IntegrityError):
            User.objects.create_user(
                username="second",
                email="Duplicate@Example.com",
                password="AnotherPass123",
            )
