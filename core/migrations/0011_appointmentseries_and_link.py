from django.db import migrations, models
import django.db.models.deletion
from django.conf import settings


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0010_make_tenant_nullable_for_tests"),
    ]

    operations = [
        migrations.CreateModel(
            name="AppointmentSeries",
            fields=[
                ("id", models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("notes", models.TextField(blank=True, null=True)),
                ("recurrence_rule", models.CharField(blank=True, max_length=100, null=True)),
                ("count", models.PositiveIntegerField(blank=True, null=True)),
                ("until", models.DateField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("tenant", models.ForeignKey(null=True, on_delete=django.db.models.deletion.CASCADE, related_name="appointment_series", to="users.tenant")),
                ("client", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="series", to=settings.AUTH_USER_MODEL)),
                ("service", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="series", to="core.service")),
                ("professional", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="series", to="core.professional")),
            ],
            options={
                "indexes": [
                    models.Index(fields=["tenant"], name="core_appoin_tenant_serie_idx"),
                    models.Index(fields=["tenant", "client"], name="core_appoin_tenant_client_idx"),
                ],
            },
        ),
        migrations.AddField(
            model_name="appointment",
            name="series",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="appointments", to="core.appointmentseries"),
        ),
    ]

