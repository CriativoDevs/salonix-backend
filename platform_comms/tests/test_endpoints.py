import pytest
from datetime import timedelta

from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from platform_comms.models import PlatformAnnouncement, PlatformAnnouncementReceipt
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

    def test_list_marks_announcement_as_delivered_for_user(
        self, api_client, user_fixture
    ):
        announcement = make_announcement()
        api_client.force_authenticate(user=user_fixture)

        url = reverse("platform-announcement-list")
        response = api_client.get(url)

        assert response.status_code == status.HTTP_200_OK
        item = response.data[0]
        assert item["is_read"] is False
        assert item["read_at"] is None

        receipt = PlatformAnnouncementReceipt.objects.get(
            announcement=announcement, user=user_fixture
        )
        assert receipt.status == PlatformAnnouncementReceipt.STATUS_DELIVERED
        assert receipt.tenant_id == user_fixture.tenant_id

    def test_list_reflects_read_state(self, api_client, user_fixture):
        announcement = make_announcement()
        receipt = PlatformAnnouncementReceipt.objects.create(
            announcement=announcement,
            user=user_fixture,
            tenant=user_fixture.tenant,
        )
        receipt.mark_read()
        api_client.force_authenticate(user=user_fixture)

        url = reverse("platform-announcement-list")
        response = api_client.get(url)

        assert response.status_code == status.HTTP_200_OK
        item = response.data[0]
        assert item["is_read"] is True
        assert item["read_at"] is not None


@pytest.mark.django_db
class TestPlatformAnnouncementReceiptEndpoints:
    def test_mark_read_requires_authentication(self, api_client):
        announcement = make_announcement()
        url = reverse("platform-announcement-mark-read", args=[announcement.pk])
        response = api_client.post(url)
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_mark_read_creates_receipt_and_sets_read(
        self, api_client, user_fixture
    ):
        announcement = make_announcement()
        api_client.force_authenticate(user=user_fixture)

        url = reverse("platform-announcement-mark-read", args=[announcement.pk])
        response = api_client.post(url)

        assert response.status_code == status.HTTP_200_OK, response.data
        assert response.data["status"] == PlatformAnnouncementReceipt.STATUS_READ

        receipt = PlatformAnnouncementReceipt.objects.get(
            announcement=announcement, user=user_fixture
        )
        assert receipt.status == PlatformAnnouncementReceipt.STATUS_READ
        assert receipt.read_at is not None

    def test_mark_read_returns_404_for_announcement_of_other_tenant(
        self, api_client, user_fixture, other_tenant_user, other_tenant
    ):
        announcement = make_announcement(
            audience_scope=PlatformAnnouncement.AUDIENCE_TENANTS
        )
        announcement.tenants.add(other_tenant)

        api_client.force_authenticate(user=user_fixture)
        url = reverse("platform-announcement-mark-read", args=[announcement.pk])
        response = api_client.post(url)

        assert response.status_code == status.HTTP_404_NOT_FOUND
        assert not PlatformAnnouncementReceipt.objects.filter(
            announcement=announcement, user=user_fixture
        ).exists()

    def test_mark_unread_resets_status(self, api_client, user_fixture):
        announcement = make_announcement()
        PlatformAnnouncementReceipt.objects.create(
            announcement=announcement,
            user=user_fixture,
            tenant=user_fixture.tenant,
            status=PlatformAnnouncementReceipt.STATUS_READ,
        )
        api_client.force_authenticate(user=user_fixture)

        url = reverse("platform-announcement-mark-unread", args=[announcement.pk])
        response = api_client.post(url)

        assert response.status_code == status.HTTP_200_OK, response.data
        assert response.data["status"] == PlatformAnnouncementReceipt.STATUS_DELIVERED

        receipt = PlatformAnnouncementReceipt.objects.get(
            announcement=announcement, user=user_fixture
        )
        assert receipt.status == PlatformAnnouncementReceipt.STATUS_DELIVERED
        assert receipt.read_at is None

    def test_mark_dismissed(self, api_client, user_fixture):
        announcement = make_announcement()
        api_client.force_authenticate(user=user_fixture)

        url = reverse("platform-announcement-mark-dismiss", args=[announcement.pk])
        response = api_client.post(url)

        assert response.status_code == status.HTTP_200_OK, response.data
        assert (
            response.data["status"] == PlatformAnnouncementReceipt.STATUS_DISMISSED
        )

    def test_mark_read_for_one_user_does_not_affect_other_user(
        self, api_client, user_fixture, other_tenant_user, other_tenant
    ):
        announcement = make_announcement(audience_scope=PlatformAnnouncement.AUDIENCE_ALL)

        api_client.force_authenticate(user=user_fixture)
        url = reverse("platform-announcement-mark-read", args=[announcement.pk])
        response = api_client.post(url)
        assert response.status_code == status.HTTP_200_OK

        other_receipt_exists = PlatformAnnouncementReceipt.objects.filter(
            announcement=announcement, user=other_tenant_user
        ).exists()
        assert other_receipt_exists is False


@pytest.mark.django_db
class TestPlatformAnnouncementUnreadCountView:
    def test_requires_authentication(self, api_client):
        url = reverse("platform-announcement-unread-count")
        response = api_client.get(url)
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_counts_active_unread_announcements(self, api_client, user_fixture):
        make_announcement(title="A")
        make_announcement(title="B")
        api_client.force_authenticate(user=user_fixture)

        url = reverse("platform-announcement-unread-count")
        response = api_client.get(url)

        assert response.status_code == status.HTTP_200_OK
        assert response.data["unread_count"] == 2

    def test_read_announcements_are_not_counted(self, api_client, user_fixture):
        announcement = make_announcement(title="A")
        make_announcement(title="B")
        api_client.force_authenticate(user=user_fixture)

        read_url = reverse("platform-announcement-mark-read", args=[announcement.pk])
        api_client.post(read_url)

        url = reverse("platform-announcement-unread-count")
        response = api_client.get(url)

        assert response.status_code == status.HTTP_200_OK
        assert response.data["unread_count"] == 1

    def test_isolation_between_tenants(
        self, api_client, user_fixture, other_tenant_user, other_tenant
    ):
        announcement = make_announcement(
            audience_scope=PlatformAnnouncement.AUDIENCE_TENANTS
        )
        announcement.tenants.add(other_tenant)

        api_client.force_authenticate(user=user_fixture)
        url = reverse("platform-announcement-unread-count")
        response = api_client.get(url)
        assert response.data["unread_count"] == 0

        api_client.force_authenticate(user=other_tenant_user)
        response_other = api_client.get(url)
        assert response_other.data["unread_count"] == 1
