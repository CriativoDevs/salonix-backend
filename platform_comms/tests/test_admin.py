from django.contrib import admin

from platform_comms.admin import PlatformAnnouncementAdmin
from platform_comms.models import PlatformAnnouncement


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
