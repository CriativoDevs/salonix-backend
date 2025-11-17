from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("users", "0020_remove_tenant_color_fields"),
    ]

    operations = [
        migrations.AddField(
            model_name="tenant",
            name="favicon_url",
            field=models.URLField(
                blank=True, null=True, help_text="URL do favicon do salão"
            ),
        ),
        migrations.AddField(
            model_name="tenant",
            name="app_name",
            field=models.CharField(
                max_length=100,
                blank=True,
                null=True,
                help_text="Nome exibido do salão/aplicativo",
            ),
        ),
    ]
