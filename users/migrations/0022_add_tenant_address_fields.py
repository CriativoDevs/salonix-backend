from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("users", "0021_add_app_name_and_favicon_url"),
    ]

    operations = [
        migrations.AddField(
            model_name="tenant",
            name="address_street",
            field=models.CharField(
                max_length=255,
                blank=True,
                null=True,
                help_text="Rua/Logradouro do estabelecimento",
            ),
        ),
        migrations.AddField(
            model_name="tenant",
            name="address_number",
            field=models.CharField(
                max_length=50,
                blank=True,
                null=True,
                help_text="Número",
            ),
        ),
        migrations.AddField(
            model_name="tenant",
            name="address_complement",
            field=models.CharField(
                max_length=255,
                blank=True,
                null=True,
                help_text="Complemento (sala, bloco, etc.)",
            ),
        ),
        migrations.AddField(
            model_name="tenant",
            name="address_neighborhood",
            field=models.CharField(
                max_length=255,
                blank=True,
                null=True,
                help_text="Bairro/Distrito",
            ),
        ),
        migrations.AddField(
            model_name="tenant",
            name="address_city",
            field=models.CharField(
                max_length=255,
                blank=True,
                null=True,
                help_text="Cidade",
            ),
        ),
        migrations.AddField(
            model_name="tenant",
            name="address_state",
            field=models.CharField(
                max_length=255,
                blank=True,
                null=True,
                help_text="Estado/Província/UF",
            ),
        ),
        migrations.AddField(
            model_name="tenant",
            name="address_zip",
            field=models.CharField(
                max_length=20,
                blank=True,
                null=True,
                help_text="CEP/Código postal",
            ),
        ),
        migrations.AddField(
            model_name="tenant",
            name="address_country",
            field=models.CharField(
                max_length=100,
                blank=True,
                null=True,
                help_text="País",
            ),
        ),
    ]

