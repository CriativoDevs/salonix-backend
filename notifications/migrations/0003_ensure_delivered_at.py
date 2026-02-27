from django.db import migrations, models


def add_delivered_at_column(apps, schema_editor):
    NotificationLog = apps.get_model("notifications", "NotificationLog")
    table_name = NotificationLog._meta.db_table
    connection = schema_editor.connection
    columns = [
        column.name for column in connection.introspection.get_table_description(
            connection.cursor(), table_name
        )
    ]
    if "delivered_at" in columns:
        return

    field = models.DateTimeField(
        null=True, blank=True, help_text="Quando foi entregue (se disponível)"
    )
    field.set_attributes_from_name("delivered_at")
    schema_editor.add_field(NotificationLog, field)


class Migration(migrations.Migration):
    dependencies = [
        ("notifications", "0002_notificationdevice_app_version_and_more"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[migrations.RunPython(add_delivered_at_column)],
            state_operations=[],
        )
    ]
