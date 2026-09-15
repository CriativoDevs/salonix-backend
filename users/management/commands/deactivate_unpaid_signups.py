from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = (
        "DEPRECATED (BE-TRIAL-02): não desativa mais nenhum tenant. "
        "Este comando existia para o fluxo antigo, com checkout no registro, "
        "onde um tenant que abandonava o checkout mantinha acesso completo "
        "indefinidamente. Com o checkout removido do registro (BE-TRIAL-01), "
        "todo tenant sem pagamento passaria por este mesmo caminho após o "
        "trial de 14 dias -- desativar a conta contradiz a decisão de produto "
        "de bloqueio brando indefinido (Tenant.is_trial_expired() + "
        "HasActiveTrialOrSubscription já bloqueiam o acesso sem apagar/"
        "desativar a conta). Mantido como no-op para não quebrar o Cron Job "
        "já configurado em produção."
    )

    def handle(self, *args, **options):
        self.stdout.write(
            self.style.WARNING(
                "deactivate_unpaid_signups está desativado (BE-TRIAL-02): "
                "o bloqueio pós-trial agora é feito por "
                "Tenant.is_trial_expired() + HasActiveTrialOrSubscription, "
                "sem desativar contas. Nenhuma ação foi tomada."
            )
        )
