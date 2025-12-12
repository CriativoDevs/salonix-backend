from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("users", "0024_tenant_feedback_digest_enabled_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="tenant",
            name="preferred_language",
            field=models.CharField(
                max_length=10,
                default="pt-PT",
                help_text="Idioma preferido do tenant (ex.: pt-PT, en)",
            ),
            preserve_default=True,
        ),
        migrations.AddField(
            model_name="customuser",
            name="language_preference",
            field=models.CharField(
                max_length=10,
                default="system",
                choices=[("system", "System"), ("pt-PT", "Português"), ("en", "English")],
                help_text="Preferência de idioma do usuário (pt-PT/en/system)",
            ),
            preserve_default=True,
        ),
    ]

