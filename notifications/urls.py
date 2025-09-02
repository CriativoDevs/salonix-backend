from django.urls import path
from .views import (
    NotificationListView,
    NotificationMarkReadView,
    NotificationMarkAllReadView,
    NotificationDeviceRegisterView,
    NotificationTestView,
    NotificationStatsView,
    NotificationLogListView,
)

urlpatterns = [
    # Notificações in-app
    path("", NotificationListView.as_view(), name="notification-list"),
    path(
        "<int:pk>/read/",
        NotificationMarkReadView.as_view(),
        name="notification-mark-read",
    ),
    path(
        "mark-all-read/",
        NotificationMarkAllReadView.as_view(),
        name="notification-mark-all-read",
    ),
    path("stats/", NotificationStatsView.as_view(), name="notification-stats"),
    # Registro de devices
    path(
        "register_device/",
        NotificationDeviceRegisterView.as_view(),
        name="notification-register-device",
    ),
    # Teste de canais
    path("test/", NotificationTestView.as_view(), name="notification-test"),
    # Logs (debug)
    path("logs/", NotificationLogListView.as_view(), name="notification-logs"),
]
