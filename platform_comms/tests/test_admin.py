import pytest
from django.contrib import admin
from django.contrib.admin.models import LogEntry
from django.contrib.contenttypes.models import ContentType
from django.contrib.messages.storage.fallback import FallbackStorage

from platform_comms.admin import PlatformAnnouncementAdmin
from platform_comms.models import PlatformAnnouncement


def _attach_messages(request):
    # ModelAdmin actions call `self.message_user`, que exige o middleware de
    # mensagens. `rf.get()` (RequestFactory) não passa pelo middleware stack,
    # então anexamos um storage de mensagens manualmente para o teste.
    setattr(request, "session", "session")
    messages = FallbackStorage(request)
    setattr(request, "_messages", messages)
    return request


def test_platform_announcement_is_registered_in_admin():
    assert admin.site.is_registered(PlatformAnnouncement)


def test_admin_exposes_tenant_filter_horizontal():
    model_admin = admin.site._registry[PlatformAnnouncement]
    assert isinstance(model_admin, PlatformAnnouncementAdmin)
    assert "tenants" in model_admin.filter_horizontal


def test_admin_save_model_sets_created_by(rf, admin_user, db):
    from platform_comms.models import PlatformAnnouncement as PA

    announcement = PA(title="Aviso", body="Corpo")
    model_admin = admin.site._registry[PA]
    request = rf.get("/admin/platform_comms/platformannouncement/add/")
    request.user = admin_user

    model_admin.save_model(request, announcement, form=None, change=False)

    assert announcement.created_by_id == admin_user.id


@pytest.mark.django_db
class TestPlatformAnnouncementAdminAudit:
    def test_publish_action_logs_entry(self, rf, admin_user):
        announcement = PlatformAnnouncement.objects.create(
            title="Manutenção",
            body="Corpo",
            status=PlatformAnnouncement.STATUS_DRAFT,
            audience_scope=PlatformAnnouncement.AUDIENCE_ALL,
        )
        model_admin = admin.site._registry[PlatformAnnouncement]
        request = _attach_messages(rf.get("/admin/platform_comms/platformannouncement/"))
        request.user = admin_user

        model_admin.publish_announcements(
            request, PlatformAnnouncement.objects.filter(pk=announcement.pk)
        )

        announcement.refresh_from_db()
        assert announcement.status == PlatformAnnouncement.STATUS_PUBLISHED

        content_type = ContentType.objects.get_for_model(PlatformAnnouncement)
        entry = LogEntry.objects.filter(
            content_type=content_type,
            object_id=str(announcement.pk),
            user=admin_user,
        ).latest("action_time")
        assert "publicad" in entry.change_message.lower()
        assert announcement.audience_scope in entry.change_message

    def test_archive_action_logs_entry(self, rf, admin_user):
        announcement = PlatformAnnouncement.objects.create(
            title="Manutenção",
            body="Corpo",
            status=PlatformAnnouncement.STATUS_PUBLISHED,
        )
        model_admin = admin.site._registry[PlatformAnnouncement]
        request = _attach_messages(rf.get("/admin/platform_comms/platformannouncement/"))
        request.user = admin_user

        model_admin.archive_announcements(
            request, PlatformAnnouncement.objects.filter(pk=announcement.pk)
        )

        announcement.refresh_from_db()
        assert announcement.status == PlatformAnnouncement.STATUS_ARCHIVED

        content_type = ContentType.objects.get_for_model(PlatformAnnouncement)
        entry = LogEntry.objects.filter(
            content_type=content_type,
            object_id=str(announcement.pk),
            user=admin_user,
        ).latest("action_time")
        assert "arquivad" in entry.change_message.lower()
