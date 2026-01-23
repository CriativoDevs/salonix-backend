import pytest
from decimal import Decimal
from django.contrib.auth import get_user_model
from users.models import Tenant, CommLedger

User = get_user_model()

@pytest.mark.django_db
class TestTenantInitialCredits:
    def test_basic_plan_initial_credits(self):
        """Testa se o plano Basic recebe 5€ de crédito inicial."""
        tenant = Tenant.objects.create(
            name="Tenant Basic",
            slug="tenant-basic-credits",
            plan_tier=Tenant.PLAN_BASIC
        )
        
        # Recarrega do banco para garantir que pegou a atualização do signal
        tenant.refresh_from_db()
        
        assert tenant.comm_credit_eur == Decimal("5.00")
        
        # Verifica Ledger
        ledger_entry = CommLedger.objects.filter(tenant=tenant).first()
        assert ledger_entry is not None
        assert ledger_entry.amount_eur == Decimal("5.00")
        assert ledger_entry.transaction_type == CommLedger.TransactionType.BONUS
        assert ledger_entry.status == CommLedger.Status.COMPLETED
        assert ledger_entry.balance_before == Decimal("0.00")
        assert ledger_entry.balance_after == Decimal("5.00")

    def test_standard_plan_initial_credits(self):
        """Testa se o plano Standard recebe 10€ de crédito inicial."""
        tenant = Tenant.objects.create(
            name="Tenant Standard",
            slug="tenant-standard-credits",
            plan_tier=Tenant.PLAN_STANDARD
        )
        
        tenant.refresh_from_db()
        
        assert tenant.comm_credit_eur == Decimal("10.00")
        
        ledger_entry = CommLedger.objects.get(tenant=tenant)
        assert ledger_entry.amount_eur == Decimal("10.00")
        assert ledger_entry.balance_after == Decimal("10.00")

    def test_pro_plan_initial_credits(self):
        """Testa se o plano Pro recebe 15€ de crédito inicial."""
        tenant = Tenant.objects.create(
            name="Tenant Pro",
            slug="tenant-pro-credits",
            plan_tier=Tenant.PLAN_PRO
        )
        
        tenant.refresh_from_db()
        
        assert tenant.comm_credit_eur == Decimal("15.00")
        
        ledger_entry = CommLedger.objects.get(tenant=tenant)
        assert ledger_entry.amount_eur == Decimal("15.00")
        assert ledger_entry.balance_after == Decimal("15.00")

    def test_update_does_not_trigger_credits(self):
        """Testa se atualizações subsequentes não duplicam créditos."""
        tenant = Tenant.objects.create(
            name="Tenant Update",
            slug="tenant-update-credits",
            plan_tier=Tenant.PLAN_BASIC
        )
        
        tenant.refresh_from_db()
        initial_credit = tenant.comm_credit_eur
        assert initial_credit == Decimal("5.00")
        
        # Atualiza o tenant
        tenant.name = "Tenant Update Changed"
        tenant.save()
        
        tenant.refresh_from_db()
        assert tenant.comm_credit_eur == initial_credit
        
        # Deve ter apenas 1 entrada no ledger
        assert CommLedger.objects.filter(tenant=tenant).count() == 1
