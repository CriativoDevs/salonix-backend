from django.db import migrations, models


def add_columns_safely(apps, schema_editor):
    Notification = apps.get_model("notifications", "Notification")
    NotificationLog = apps.get_model("notifications", "NotificationLog")
    Appointment = apps.get_model("core", "Appointment")
    SalonCustomer = apps.get_model("core", "SalonCustomer")
    connection = schema_editor.connection

    # Notification table
    notif_columns = [
        column.name
        for column in connection.introspection.get_table_description(
            connection.cursor(), Notification._meta.db_table
        )
    ]
    if "customer_id" not in notif_columns:
        field = models.ForeignKey(
            SalonCustomer,
            on_delete=models.CASCADE,
            related_name="notifications",
            null=True,
            blank=True,
        )
        field.set_attributes_from_name("customer")
        schema_editor.add_field(Notification, field)
    if "appointment_id" not in notif_columns:
        field = models.ForeignKey(
            Appointment,
            on_delete=models.SET_NULL,
            null=True,
            blank=True,
            related_name="notifications",
        )
        field.set_attributes_from_name("appointment")
        schema_editor.add_field(Notification, field)

    # NotificationLog table
    log_columns = [
        column.name
        for column in connection.introspection.get_table_description(
            connection.cursor(), NotificationLog._meta.db_table
        )
    ]
    if "customer_id" not in log_columns:
        field = models.ForeignKey(
            SalonCustomer,
            on_delete=models.CASCADE,
            related_name="notification_logs",
            null=True,
            blank=True,
        )
        field.set_attributes_from_name("customer")
        schema_editor.add_field(NotificationLog, field)
    if "appointment_id" not in log_columns:
        field = models.ForeignKey(
            Appointment,
            on_delete=models.SET_NULL,
            null=True,
            blank=True,
            related_name="notification_logs",
        )
        field.set_attributes_from_name("appointment")
        schema_editor.add_field(NotificationLog, field)


class Migration(migrations.Migration):
    atomic = False
    dependencies = [
        ("notifications", "0003_ensure_delivered_at"),
    ]

    operations = [
        migrations.RunPython(add_columns_safely),
        migrations.AlterField(
            model_name="notification",
            name="user",
            field=models.ForeignKey(
                blank=True,
                help_text="Usuário que recebe a notificação",
                null=True,
                on_delete=models.deletion.CASCADE,
                related_name="notifications",
                to="users.customuser",
            ),
        ),
        migrations.AlterField(
            model_name="notificationlog",
            name="user",
            field=models.ForeignKey(
                blank=True,
                help_text="Usuário destinatário",
                null=True,
                on_delete=models.deletion.CASCADE,
                related_name="notification_logs",
                to="users.customuser",
            ),
        ),
    ]
