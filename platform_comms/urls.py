from django.urls import path

from platform_comms.views import (
    PlatformAnnouncementListView,
    PlatformAnnouncementMarkDismissedView,
    PlatformAnnouncementMarkReadView,
    PlatformAnnouncementMarkUnreadView,
    PlatformAnnouncementUnreadCountView,
)

urlpatterns = [
    path(
        "announcements/",
        PlatformAnnouncementListView.as_view(),
        name="platform-announcement-list",
    ),
    path(
        "announcements/unread-count/",
        PlatformAnnouncementUnreadCountView.as_view(),
        name="platform-announcement-unread-count",
    ),
    path(
        "announcements/<int:pk>/read/",
        PlatformAnnouncementMarkReadView.as_view(),
        name="platform-announcement-mark-read",
    ),
    path(
        "announcements/<int:pk>/unread/",
        PlatformAnnouncementMarkUnreadView.as_view(),
        name="platform-announcement-mark-unread",
    ),
    path(
        "announcements/<int:pk>/dismiss/",
        PlatformAnnouncementMarkDismissedView.as_view(),
        name="platform-announcement-mark-dismiss",
    ),
]
