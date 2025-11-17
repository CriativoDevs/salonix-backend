from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("users", "0011_customuser_users_customuser_email_ci_unique"),
    ]

    operations = [
        migrations.AddField(
            model_name="tenant",
            name="auto_invite_enabled",
            field=models.BooleanField(
                default=False,
                help_text="Envia automaticamente convite do PWA Cliente para novos clientes",
            ),
        ),
    ]
