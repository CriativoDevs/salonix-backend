from django.apps import AppConfig
from typing import ClassVar


class ReportsConfig(AppConfig):
    default_auto_field: ClassVar[str] = 'django.db.models.BigAutoField'
    name = 'reports'
