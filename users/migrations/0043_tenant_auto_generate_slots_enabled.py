from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("users", "0042_tenant_comm_auto_renew_consecutive_failures"),
    ]

    operations = [
        migrations.AddField(
            model_name="tenant",
            name="auto_generate_slots_enabled",
            field=models.BooleanField(
                default=False,
                help_text=(
                    "Gera automaticamente slots do próximo mês (requer horário "
                    "de funcionamento configurado). Rodado via management "
                    "command auto_generate_monthly_slots (Cron Job no Railway)."
                ),
            ),
        ),
    ]
