from django.db import migrations


def remove_superuser_flag(apps, schema_editor):
    CustomUser = apps.get_model("users", "CustomUser")
    CustomUser.objects.filter(
        is_superuser=True,
        tenant__isnull=False,
    ).update(is_superuser=False)


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("users", "0014_rename_users_staff_tenant_idx_users_tenan_tenant__61c8d0_idx_and_more"),
    ]

    operations = [
        migrations.RunPython(remove_superuser_flag, noop),
    ]
