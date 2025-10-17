import string

from django.contrib.auth.models import BaseUserManager
from django.utils.crypto import get_random_string


class CustomUserManager(BaseUserManager):
    def create_user(self, username, email, password=None, **extra_fields):
        if not username:
            raise ValueError("The Username must be set")
        if not email:
            raise ValueError("The Email must be set")
        email = self.normalize_email(email)
        user = self.model(username=username, email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, username, email, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        extra_fields.setdefault("is_active", True)

        return self.create_user(username, email, password, **extra_fields)

    def make_random_password(
        self,
        length: int = 12,
        allowed_chars: str = string.ascii_letters + string.digits,
    ) -> str:
        """
        Replica do helper removido do Django 5.x.
        """
        return get_random_string(length, allowed_chars)
