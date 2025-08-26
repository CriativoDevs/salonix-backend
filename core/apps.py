from django.apps import AppConfig


class CoreConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "core"

    def ready(self) -> None:
        try:
            import core.signals  # noqa: F401
        except ModuleNotFoundError:
            # Sem sinais definidos (ambiente atual). Ignora.
            pass
