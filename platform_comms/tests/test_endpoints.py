import pytest
from datetime import timedelta

from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from platform_comms.models import PlatformAnnouncement
from users.models import Tenant, CustomUser, TenantStaffMember


@pytest.fixture
def api_client():
    return APIClient()


@pytest.fixture
def other_tenant(db):
    return Tenant.objects.create(
        slug="tenant-b",
        name="Tenant B",
        plan_tier=Tenant.PLAN_BASIC,
    )


@pytest.fixture
def other_tenant_user(db, other_tenant):
    user = CustomUser.objects.create_user(
        username="otheruser", email="other@example.com", password="testpass"
    )
    user.tenant = other_tenant
    user.save()
    TenantStaffMember.objects.create(
        tenant=other_tenant,
        user=user,
        role=TenantStaffMember.Role.OWNER,
        status=TenantStaffMember.Status.ACTIVE,
    )
    return user


def make_announcement(**overrides):
    defaults = dict(
        title="Manutenção programada",
        body="O sistema ficará indisponível por 10 minutos.",
        status=PlatformAnnouncement.STATUS_PUBLISHED,
        publish_at=timezone.now() - timedelta(hours=1),
    )
    defaults.update(overrides)
    return PlatformAnnouncement.objects.create(**defaults)


@pytest.mark.django_db
class TestPlatformAnnouncementListView:
    def test_requires_authentication(self, api_client):
        url = reverse("platform-announcement-list")
        response = api_client.get(url)
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_returns_active_announcement_for_tenant(
        self, api_client, user_fixture
    ):
        announcement = make_announcement()
        api_client.force_authenticate(user=user_fixture)

        url = reverse("platform-announcement-list")
        response = api_client.get(url)

        assert response.status_code == status.HTTP_200_OK
        titles = [item["title"] for item in response.data]
        assert announcement.title in titles

    def test_excludes_draft_announcements(self, api_client, user_fixture):
        make_announcement(status=PlatformAnnouncement.STATUS_DRAFT)
        api_client.force_authenticate(user=user_fixture)

        url = reverse("platform-announcement-list")
        response = api_client.get(url)

        assert response.status_code == status.HTTP_200_OK
        assert response.data == []

    def test_excludes_out_of_window_announcements(self, api_client, user_fixture):
        make_announcement(
            publish_at=timezone.now() - timedelta(days=2),
            expire_at=timezone.now() - timedelta(days=1),
        )
        api_client.force_authenticate(user=user_fixture)

        url = reverse("platform-announcement-list")
        response = api_client.get(url)

        assert response.status_code == status.HTTP_200_OK
        assert response.data == []

    def test_does_not_leak_other_tenant_specific_announcement(
        self, api_client, user_fixture, other_tenant_user, other_tenant
    ):
        announcement = make_announcement(
            audience_scope=PlatformAnnouncement.AUDIENCE_TENANTS
        )
        announcement.tenants.add(other_tenant)

        api_client.force_authenticate(user=user_fixture)
        url = reverse("platform-announcement-list")
        response = api_client.get(url)

        assert response.status_code == status.HTTP_200_OK
        titles = [item["title"] for item in response.data]
        assert announcement.title not in titles

        # Mas aparece para o tenant correto.
        api_client.force_authenticate(user=other_tenant_user)
        response_other = api_client.get(url)
        assert response_other.status_code == status.HTTP_200_OK, response_other.data
        titles_other = [item["title"] for item in response_other.data]
        assert announcement.title in titles_other

    def test_response_does_not_expose_segmentation_fields(
        self, api_client, user_fixture
    ):
        make_announcement()
        api_client.force_authenticate(user=user_fixture)

        url = reverse("platform-announcement-list")
        response = api_client.get(url)

        assert response.status_code == status.HTTP_200_OK
        item = response.data[0]
        assert "tenants" not in item
        assert "target_plans" not in item
        assert "environments" not in item
