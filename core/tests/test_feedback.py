import pytest
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient
from django.test.utils import override_settings

from users.models import Tenant, CustomUser, TenantStaffMember
from core.models import Feedback, SalonCustomer


@pytest.mark.django_db
def test_create_feedback_requires_owner_and_captcha_bypass():
    tenant = Tenant.objects.create(name="Salon", slug="salon")
    owner = CustomUser.objects.create_user(
        username="owner", email="owner@x.test", password="x", tenant=tenant
    )
    TenantStaffMember.objects.create(
        tenant=tenant, user=owner, role=TenantStaffMember.Role.OWNER
    )
    manager = CustomUser.objects.create_user(
        username="mgr", email="mgr@x.test", password="x", tenant=tenant
    )
    TenantStaffMember.objects.create(
        tenant=tenant, user=manager, role=TenantStaffMember.Role.MANAGER
    )

    client = APIClient()
    client.force_authenticate(owner)

    with override_settings(CAPTCHA_ENABLED=True, CAPTCHA_BYPASS_TOKEN="TEST"):
        url = reverse("feedback-list-create")
        payload = {
            "tenant": tenant.id,
            "category": "praise",
            "rating": 5,
            "message": "Excelente",
            "is_anonymous": True,
        }
        r = client.post(url, payload, format="json", HTTP_X_CAPTCHA_VALUE="TEST")
        assert r.status_code == status.HTTP_201_CREATED

    client.force_authenticate(manager)
    with override_settings(CAPTCHA_ENABLED=False):
        r2 = client.post(url, payload, format="json")
        assert r2.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.django_db
def test_create_feedback_captcha_invalid():
    tenant = Tenant.objects.create(name="Salon", slug="salon")
    owner = CustomUser.objects.create_user(
        username="owner", email="owner@x.test", password="x", tenant=tenant
    )
    TenantStaffMember.objects.create(
        tenant=tenant, user=owner, role=TenantStaffMember.Role.OWNER
    )
    client = APIClient()
    client.force_authenticate(owner)
    url = reverse("feedback-list-create")
    payload = {"tenant": tenant.id, "category": "bug", "rating": 1, "message": "erro"}
    with override_settings(CAPTCHA_ENABLED=True, CAPTCHA_BYPASS_TOKEN="OTHER"):
        r = client.post(url, payload, format="json")
        assert r.status_code == status.HTTP_400_BAD_REQUEST
        assert r.data.get("detail") == "Captcha inválido."


@pytest.mark.django_db
def test_create_feedback_throttled_user_scope():
    tenant = Tenant.objects.create(name="Salon", slug="salon")
    owner = CustomUser.objects.create_user(
        username="owner", email="owner@x.test", password="x", tenant=tenant
    )
    TenantStaffMember.objects.create(
        tenant=tenant, user=owner, role=TenantStaffMember.Role.OWNER
    )
    client = APIClient()
    client.force_authenticate(owner)
    url = reverse("feedback-list-create")
    payload = {
        "tenant": tenant.id,
        "category": "app",
        "rating": 3,
        "message": "ok",
        "is_anonymous": True,
    }
    with override_settings(
        CACHES={
            "default": {
                "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
                "LOCATION": "feedback-throttle",
            }
        },
        REST_FRAMEWORK={
            "DEFAULT_AUTHENTICATION_CLASSES": [
                "rest_framework_simplejwt.authentication.JWTAuthentication",
            ],
            "DEFAULT_PERMISSION_CLASSES": [
                "rest_framework.permissions.IsAuthenticated",
            ],
            "DEFAULT_THROTTLE_CLASSES": [
                "rest_framework.throttling.UserRateThrottle",
                "rest_framework.throttling.ScopedRateThrottle",
            ],
            "DEFAULT_THROTTLE_RATES": {
                "user": "1000/day",
                "feedback_create": "2/min",
            },
        },
        CAPTCHA_ENABLED=False,
    ):
        assert client.post(url, payload, format="json").status_code == 201
        payload2 = dict(payload)
        payload2["message"] = "ok2"
        assert client.post(url, payload2, format="json").status_code == 201
        payload3 = dict(payload)
        payload3["message"] = "ok3"
        assert client.post(url, payload3, format="json").status_code == 429


@pytest.mark.django_db
def test_create_feedback_duplicate_recent_rejected():
    tenant = Tenant.objects.create(name="Salon", slug="salon")
    owner = CustomUser.objects.create_user(
        username="owner", email="owner@x.test", password="x", tenant=tenant
    )
    TenantStaffMember.objects.create(
        tenant=tenant, user=owner, role=TenantStaffMember.Role.OWNER
    )
    client = APIClient()
    client.force_authenticate(owner)
    url = reverse("feedback-list-create")
    payload = {
        "tenant": tenant.id,
        "category": "app",
        "rating": 1,
        "message": "erro",
        "is_anonymous": True,
    }
    with override_settings(CAPTCHA_ENABLED=False):
        r1 = client.post(url, payload, format="json")
        assert r1.status_code == 201
        r2 = client.post(url, payload, format="json")
        assert r2.status_code == 429


@pytest.mark.django_db
def test_list_feedback_filters_and_permissions():
    tenant = Tenant.objects.create(name="Salon", slug="salon")
    owner = CustomUser.objects.create_user(
        username="owner", email="owner@x.test", password="x", tenant=tenant
    )
    TenantStaffMember.objects.create(
        tenant=tenant, user=owner, role=TenantStaffMember.Role.OWNER
    )
    manager = CustomUser.objects.create_user(
        username="mgr", email="mgr@x.test", password="x", tenant=tenant
    )
    TenantStaffMember.objects.create(
        tenant=tenant, user=manager, role=TenantStaffMember.Role.MANAGER
    )
    customer = CustomUser.objects.create_user(
        username="cust", email="cust@x.test", password="x", tenant=tenant
    )
    sc = SalonCustomer.objects.create(
        tenant=tenant, name="Cliente X", email=customer.email
    )
    Feedback.objects.create(
        tenant=tenant, customer=sc, category="app", rating=1, message="a"
    )
    Feedback.objects.create(
        tenant=tenant, customer=sc, category="praise", rating=5, message="b"
    )
    Feedback.objects.create(tenant=tenant, category="praise", rating=4, message="c")

    client = APIClient()
    client.force_authenticate(manager)
    url = reverse("feedback-list-create")
    r = client.get(url + "?category=praise&min_rating=4")
    assert r.status_code == 200
    assert len(r.data) == 2

    client.force_authenticate(owner)
    r2 = client.get(url + "?rating=1")
    assert r2.status_code == 200
    assert len(r2.data) == 1


@pytest.mark.django_db
def test_detail_feedback_permissions():
    tenant = Tenant.objects.create(name="Salon", slug="salon")
    owner = CustomUser.objects.create_user(
        username="owner", email="owner@x.test", password="x", tenant=tenant
    )
    TenantStaffMember.objects.create(
        tenant=tenant, user=owner, role=TenantStaffMember.Role.OWNER
    )
    collab = CustomUser.objects.create_user(
        username="collab", email="c@x.test", password="x", tenant=tenant
    )
    TenantStaffMember.objects.create(
        tenant=tenant, user=collab, role=TenantStaffMember.Role.COLLABORATOR
    )
    f = Feedback.objects.create(tenant=tenant, category="other", rating=3, message="m")
    client = APIClient()
    client.force_authenticate(owner)
    url = reverse("feedback-detail", kwargs={"pk": f.id})
    r = client.get(url)
    assert r.status_code == 200
    client.force_authenticate(collab)
    r2 = client.get(url)
    assert r2.status_code == 403


@pytest.mark.django_db
def test_create_feedback_anonymous():
    tenant = Tenant.objects.create(name="Salon", slug="salon")
    owner = CustomUser.objects.create_user(
        username="owner", email="owner@x.test", password="x", tenant=tenant
    )
    TenantStaffMember.objects.create(
        tenant=tenant, user=owner, role=TenantStaffMember.Role.OWNER
    )
    client = APIClient()
    client.force_authenticate(owner)
    url = reverse("feedback-list-create")
    payload = {
        "tenant": tenant.id,
        "category": "praise",
        "rating": 5,
        "message": "ok",
        "is_anonymous": True,
    }
    with override_settings(CAPTCHA_ENABLED=False):
        r = client.post(url, payload, format="json")
        assert r.status_code == 201
