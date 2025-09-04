import pytest
from django.urls import reverse
from rest_framework.test import APIClient
from rest_framework import status
from django.contrib.auth import get_user_model

User = get_user_model()


@pytest.mark.django_db
class TestAuthEndpoints:

    def setup_method(self):
        self.client = APIClient()
        self.register_url = reverse("register")
        self.token_url = reverse("token_obtain_pair")

    def test_successful_registration(self):
        payload = {
            "username": "lucas",
            "email": "lucas@salonix.com",
            "password": "strongpassword123",
        }
        response = self.client.post(self.register_url, data=payload)
        assert response.status_code == status.HTTP_201_CREATED
        assert "id" in response.data

    def test_registration_missing_fields(self):
        response = self.client.post(self.register_url, data={"email": "x@x.com"})
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        # Com novo sistema de erros, a estrutura mudou
        assert "error" in response.data
        assert "username" in response.data["error"]["details"]
        assert "password" in response.data["error"]["details"]

    def test_successful_login(self):
        User.objects.create_user(
            username="lucas",
            email="lucas@example.com",
            password="testpass123",
        )
        payload = {"email": "lucas@example.com", "password": "testpass123"}
        response = self.client.post(self.token_url, data=payload)
        assert response.status_code == status.HTTP_200_OK
        assert "access" in response.data
        assert "refresh" in response.data

    def test_login_with_wrong_password(self):
        User.objects.create_user(
            username="lucas",
            email="lucas@example.com",
            password="testpass123",
        )
        payload = {"email": "lucas@example.com", "password": "wrongpassword"}
        response = self.client.post(self.token_url, data=payload)
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_login_with_nonexistent_user(self):
        payload = {"email": "doesnotexist@example.com", "password": "irrelevant"}
        response = self.client.post(self.token_url, data=payload)
        assert response.status_code == status.HTTP_401_UNAUTHORIZED
