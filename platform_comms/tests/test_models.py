import pytest
from datetime import timedelta

from django.db import IntegrityError
from django.utils import timezone

from platform_comms.models import PlatformAnnouncement, PlatformAnnouncementReceipt
from users.models import CustomUser, Tenant


@pytest.fixture
def other_tenant(db):
    return Tenant.objects.create(
        slug="tenant-b",
        name="Tenant B",
        plan_tier=Tenant.PLAN_BASIC,
    )


def make_announcement(**overrides):
    defaults = dict(
        title="Manutenção programada",
        body="O sistema ficará indisponível por 10 minutos.",
        announcement_type=PlatformAnnouncement.TYPE_MAINTENANCE,
        priority=PlatformAnnouncement.PRIORITY_HIGH,
        status=PlatformAnnouncement.STATUS_PUBLISHED,
        publish_at=timezone.now() - timedelta(hours=1),
    )
    defaults.update(overrides)
    return PlatformAnnouncement.objects.create(**defaults)


@pytest.mark.django_db
class TestPlatformAnnouncementModel:
    def test_create_defaults_to_draft_and_all_tenants(self):
        announcement = PlatformAnnouncement.objects.create(
            title="Novidade",
            body="Nova funcionalidade disponível.",
        )
        assert announcement.status == PlatformAnnouncement.STATUS_DRAFT
        assert announcement.audience_scope == PlatformAnnouncement.AUDIENCE_ALL
        assert announcement.environments == []
        assert announcement.target_plans == []

    def test_publish_sets_status(self):
        announcement = make_announcement(status=PlatformAnnouncement.STATUS_DRAFT)
        announcement.publish()
        announcement.refresh_from_db()
        assert announcement.status == PlatformAnnouncement.STATUS_PUBLISHED

    def test_archive_sets_status(self):
        announcement = make_announcement()
        announcement.archive()
        announcement.refresh_from_db()
        assert announcement.status == PlatformAnnouncement.STATUS_ARCHIVED

    def test_is_within_window_true_when_no_expire(self):
        announcement = make_announcement(expire_at=None)
        assert announcement.is_within_window is True

    def test_is_within_window_false_before_publish(self):
        announcement = make_announcement(
            publish_at=timezone.now() + timedelta(days=1)
        )
        assert announcement.is_within_window is False

    def test_is_within_window_false_after_expire(self):
        announcement = make_announcement(
            publish_at=timezone.now() - timedelta(days=2),
            expire_at=timezone.now() - timedelta(days=1),
        )
        assert announcement.is_within_window is False


@pytest.mark.django_db
class TestPlatformAnnouncementManagerActiveForTenant:
    def test_draft_is_not_active(self, tenant_fixture):
        make_announcement(status=PlatformAnnouncement.STATUS_DRAFT)
        result = PlatformAnnouncement.objects.active_for_tenant(tenant_fixture)
        assert result.count() == 0

    def test_archived_is_not_active(self, tenant_fixture):
        make_announcement(status=PlatformAnnouncement.STATUS_ARCHIVED)
        result = PlatformAnnouncement.objects.active_for_tenant(tenant_fixture)
        assert result.count() == 0

    def test_future_publish_at_excluded(self, tenant_fixture):
        make_announcement(publish_at=timezone.now() + timedelta(days=1))
        result = PlatformAnnouncement.objects.active_for_tenant(tenant_fixture)
        assert result.count() == 0

    def test_past_expire_at_excluded(self, tenant_fixture):
        make_announcement(
            publish_at=timezone.now() - timedelta(days=2),
            expire_at=timezone.now() - timedelta(days=1),
        )
        result = PlatformAnnouncement.objects.active_for_tenant(tenant_fixture)
        assert result.count() == 0

    def test_within_window_included(self, tenant_fixture):
        announcement = make_announcement(
            publish_at=timezone.now() - timedelta(hours=1),
            expire_at=timezone.now() + timedelta(hours=1),
        )
        result = PlatformAnnouncement.objects.active_for_tenant(tenant_fixture)
        assert list(result) == [announcement]

    def test_no_expire_at_stays_active(self, tenant_fixture):
        announcement = make_announcement(expire_at=None)
        result = PlatformAnnouncement.objects.active_for_tenant(tenant_fixture)
        assert list(result) == [announcement]

    def test_audience_all_tenants_visible_to_any_tenant(
        self, tenant_fixture, other_tenant
    ):
        announcement = make_announcement(
            audience_scope=PlatformAnnouncement.AUDIENCE_ALL
        )
        assert list(
            PlatformAnnouncement.objects.active_for_tenant(tenant_fixture)
        ) == [announcement]
        assert list(
            PlatformAnnouncement.objects.active_for_tenant(other_tenant)
        ) == [announcement]

    def test_audience_specific_tenants_isolation(self, tenant_fixture, other_tenant):
        announcement = make_announcement(
            audience_scope=PlatformAnnouncement.AUDIENCE_TENANTS
        )
        announcement.tenants.add(tenant_fixture)

        assert list(
            PlatformAnnouncement.objects.active_for_tenant(tenant_fixture)
        ) == [announcement]
        assert list(PlatformAnnouncement.objects.active_for_tenant(other_tenant)) == []

    def test_audience_specific_plans(self, tenant_fixture, other_tenant):
        # tenant_fixture usa plan_tier="pro" (ver conftest); other_tenant usa "basic".
        announcement = make_announcement(
            audience_scope=PlatformAnnouncement.AUDIENCE_PLANS,
            target_plans=[Tenant.PLAN_BASIC],
        )

        assert list(PlatformAnnouncement.objects.active_for_tenant(tenant_fixture)) == []
        assert list(
            PlatformAnnouncement.objects.active_for_tenant(other_tenant)
        ) == [announcement]

    def test_environment_filter_empty_shows_everywhere(self, tenant_fixture):
        announcement = make_announcement(environments=[])
        result = PlatformAnnouncement.objects.active_for_tenant(
            tenant_fixture, environment="prod"
        )
        assert list(result) == [announcement]

    def test_environment_filter_excludes_other_environment(self, tenant_fixture):
        make_announcement(environments=["prod"])
        result = PlatformAnnouncement.objects.active_for_tenant(
            tenant_fixture, environment="dev"
        )
        assert list(result) == []

    def test_environment_filter_matches_target_environment(self, tenant_fixture):
        announcement = make_announcement(environments=["dev", "uat"])
        result = PlatformAnnouncement.objects.active_for_tenant(
            tenant_fixture, environment="dev"
        )
        assert list(result) == [announcement]


@pytest.mark.django_db
class TestPlatformAnnouncementReceiptModel:
    def test_defaults_to_delivered(self, tenant_fixture, user_fixture):
        announcement = make_announcement()
        receipt = PlatformAnnouncementReceipt.objects.create(
            announcement=announcement, user=user_fixture, tenant=tenant_fixture
        )
        assert receipt.status == PlatformAnnouncementReceipt.STATUS_DELIVERED
        assert receipt.delivered_at is not None
        assert receipt.read_at is None
        assert receipt.dismissed_at is None

    def test_mark_read_sets_status_and_timestamp(self, tenant_fixture, user_fixture):
        announcement = make_announcement()
        receipt = PlatformAnnouncementReceipt.objects.create(
            announcement=announcement, user=user_fixture, tenant=tenant_fixture
        )
        receipt.mark_read()
        receipt.refresh_from_db()
        assert receipt.status == PlatformAnnouncementReceipt.STATUS_READ
        assert receipt.read_at is not None

    def test_mark_unread_clears_read_at(self, tenant_fixture, user_fixture):
        announcement = make_announcement()
        receipt = PlatformAnnouncementReceipt.objects.create(
            announcement=announcement, user=user_fixture, tenant=tenant_fixture
        )
        receipt.mark_read()
        receipt.mark_unread()
        receipt.refresh_from_db()
        assert receipt.status == PlatformAnnouncementReceipt.STATUS_DELIVERED
        assert receipt.read_at is None

    def test_mark_dismissed_sets_status_and_timestamp(
        self, tenant_fixture, user_fixture
    ):
        announcement = make_announcement()
        receipt = PlatformAnnouncementReceipt.objects.create(
            announcement=announcement, user=user_fixture, tenant=tenant_fixture
        )
        receipt.mark_dismissed()
        receipt.refresh_from_db()
        assert receipt.status == PlatformAnnouncementReceipt.STATUS_DISMISSED
        assert receipt.dismissed_at is not None

    def test_unique_per_announcement_and_user(self, tenant_fixture, user_fixture):
        announcement = make_announcement()
        PlatformAnnouncementReceipt.objects.create(
            announcement=announcement, user=user_fixture, tenant=tenant_fixture
        )
        with pytest.raises(IntegrityError):
            PlatformAnnouncementReceipt.objects.create(
                announcement=announcement, user=user_fixture, tenant=tenant_fixture
            )

    def test_same_announcement_different_users_independent(
        self, tenant_fixture, user_fixture, other_tenant
    ):
        other_user = CustomUser.objects.create_user(
            username="other-receipt-user",
            email="other-receipt-user@example.com",
            password="testpass",
        )
        announcement = make_announcement()
        receipt_a = PlatformAnnouncementReceipt.objects.create(
            announcement=announcement, user=user_fixture, tenant=tenant_fixture
        )
        receipt_b = PlatformAnnouncementReceipt.objects.create(
            announcement=announcement, user=other_user, tenant=other_tenant
        )
        receipt_a.mark_read()

        receipt_b.refresh_from_db()
        assert receipt_b.status == PlatformAnnouncementReceipt.STATUS_DELIVERED
