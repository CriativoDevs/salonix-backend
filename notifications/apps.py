from django.apps import AppConfig
from typing import ClassVar


class NotificationsConfig(AppConfig):
    default_auto_field: ClassVar[str] = "django.db.models.BigAutoField"
    name = "notifications"
    verbose_name = "Notifications"

    def ready(self):
        """Importar signals quando a app estiver pronta"""
        # Garantir registro dos receivers
        from . import signals  # noqa: F401
