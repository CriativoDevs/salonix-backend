from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("users", "0022_add_tenant_address_fields"),
    ]

    operations = [
        migrations.AddField(
            model_name="tenant",
            name="contact_email",
            field=models.EmailField(
                blank=True,
                null=True,
                max_length=254,
                help_text="Email de contato público do salão",
            ),
        ),
        migrations.AddField(
            model_name="tenant",
            name="contact_phone",
            field=models.CharField(
                blank=True,
                null=True,
                max_length=32,
                help_text="Telefone de contato público do salão (E.164 ou local)",
            ),
        ),
    ]
