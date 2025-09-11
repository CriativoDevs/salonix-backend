from django.apps import AppConfig
from typing import ClassVar


class SalonixBackendConfig(AppConfig):
    default_auto_field: ClassVar[str] = "django.db.models.BigAutoField"
    name = "salonix_backend"
    verbose_name = "Salonix Backend"
