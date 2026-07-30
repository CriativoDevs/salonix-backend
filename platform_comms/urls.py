from django.urls import path

from platform_comms.views import PlatformAnnouncementListView

urlpatterns = [
    path(
        "announcements/",
        PlatformAnnouncementListView.as_view(),
        name="platform-announcement-list",
    ),
]
