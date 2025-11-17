from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("users", "0019_alter_commledger_options_english"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="tenant",
            name="primary_color",
        ),
        migrations.RemoveField(
            model_name="tenant",
            name="secondary_color",
        ),
    ]