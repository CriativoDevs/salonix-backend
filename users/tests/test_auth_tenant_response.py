import pytest
from django.urls import reverse
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient
from rest_framework import status
from users.models import Tenant

User = get_user_model()


@pytest.mark.django_db
def test_register_returns_tenant_meta():
    """
    Verifica se o endpoint de registro retorna o objeto tenant completo com slug e metadados.
    """
    client = APIClient()
    url = reverse("users:register")
    payload = {
        "username": "newuser",
        "email": "newuser@example.com",
        "password": "Password123!",
        "salon_name": "New Salon",
        "plan": "founder",
    }

    response = client.post(url, payload)

    assert response.status_code == status.HTTP_201_CREATED
    data = response.json()

    # Verify Tenant Structure
    assert "tenant" in data
    tenant = data["tenant"]

    # Required Fields
    assert "slug" in tenant
    assert "name" in tenant
    assert tenant["name"] == "New Salon"

    # Meta Fields (BE-233)
    assert "branding" in tenant
    assert "logo_url" in tenant["branding"]
    assert "app_name" in tenant["branding"]

    assert "plan" in tenant
    assert tenant["plan"]["billing_mode"] == Tenant.BILLING_MODE_STRIPE

    assert "feature_flags" in tenant
    assert isinstance(tenant["feature_flags"], dict)


@pytest.mark.django_db
def test_login_returns_tenant_meta():
    """
    Verifica se o endpoint de login retorna o objeto tenant completo.
    """
    client = APIClient()
    # Setup User and Tenant
    user = User.objects.create_user(
        username="loginuser", email="login@example.com", password="Password123!"
    )
    # Ensure tenant exists (created via signal or manual in this test context?)
    # Users created via create_user might not have tenant if not going through serializer logic.
    # Let's use the registration serializer logic or manually create tenant.
    tenant = Tenant.objects.create(name="Login Salon", slug="login-salon")
    user.tenant = tenant
    user.save()

    url = reverse("users:token_obtain_pair")
    payload = {"email": "login@example.com", "password": "Password123!"}

    response = client.post(url, payload)

    assert response.status_code == status.HTTP_200_OK
    data = response.json()

    # Verify Tenant Structure
    assert "tenant" in data
    tenant_data = data["tenant"]

    assert tenant_data["slug"] == "login-salon"
    assert "branding" in tenant_data
    assert "feature_flags" in tenant_data
    assert tenant_data["plan"]["billing_mode"] == Tenant.BILLING_MODE_STRIPE


@pytest.mark.django_db
def test_web_login_returns_promotional_tenant_meta_without_subscription():
    client = APIClient()
    tenant = Tenant.objects.create(
        name="Promo Web Salon",
        slug="promo-web-salon",
        billing_mode=Tenant.BILLING_MODE_PROMOTIONAL,
        plan_tier=Tenant.PLAN_BASIC,
    )
    user = User.objects.create_user(
        username="promo-web-user",
        email="promo-web@example.com",
        password="Password123!",
        tenant=tenant,
    )

    url = reverse("users:token_obtain_pair")
    response = client.post(
        url,
        {"email": user.email, "password": "Password123!"},
    )

    assert response.status_code == status.HTTP_200_OK
    tenant_data = response.json()["tenant"]
    assert tenant_data["slug"] == tenant.slug
    assert tenant_data["plan"]["billing_mode"] == Tenant.BILLING_MODE_PROMOTIONAL
