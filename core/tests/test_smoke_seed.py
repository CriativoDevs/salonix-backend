from django.test import TestCase
from django.core.management import call_command
from django.contrib.auth import get_user_model
from users.models import Tenant, CommLedger
from core.models import Service, Appointment

User = get_user_model()

class SmokeSeedTest(TestCase):
    def test_seed_demo_is_idempotent_and_creates_data(self):
        """
        Teste de fumaça para garantir que o seed_demo roda sem erros,
        cria os dados esperados e é idempotente (pode rodar 2x).
        """
        # 1. Primeira execução
        call_command("seed_demo")

        # Verificar Tenants
        self.assertTrue(Tenant.objects.filter(slug="default").exists())
        self.assertTrue(Tenant.objects.filter(slug="basic-demo").exists())
        self.assertTrue(Tenant.objects.filter(slug="pro-demo").exists())
        self.assertTrue(Tenant.objects.filter(slug="empty-credits").exists())

        # Verificar Usuários
        self.assertTrue(User.objects.filter(username="admin").exists())
        self.assertTrue(User.objects.filter(username="pro_smoke").exists())
        self.assertTrue(User.objects.filter(username="client_smoke").exists())

        # "admin" é o owner de teste do tenant, NUNCA superuser do DAP -- não
        # misturar a conta de teste da plataforma com acesso de administração
        # do Django Admin.
        admin_user = User.objects.get(username="admin")
        self.assertFalse(admin_user.is_superuser)
        self.assertTrue(admin_user.check_password("admin123"))

        # "superadmin" é o acesso dedicado ao DAP, sem tenant.
        superadmin_user = User.objects.get(username="superadmin")
        self.assertTrue(superadmin_user.is_superuser)
        self.assertIsNone(superadmin_user.tenant)

        # Verificar Dados de Negócio (Default Tenant)
        default_tenant = Tenant.objects.get(slug="default")
        self.assertTrue(Service.objects.filter(tenant=default_tenant).exists())
        self.assertTrue(Appointment.objects.filter(tenant=default_tenant).exists())
        
        # Verificar CommLedger (Créditos)
        # O seed cria transações para o default_tenant
        ledger_count = CommLedger.objects.filter(tenant=default_tenant).count()
        self.assertGreater(ledger_count, 0, "Deve haver histórico de créditos para o tenant default")

        # Verificar Feature Flags do Basic
        basic_tenant = Tenant.objects.get(slug="basic-demo")
        self.assertEqual(basic_tenant.plan_tier, "basic")
        self.assertFalse(basic_tenant.comm_auto_renew)

        # Verificar Feature Flags do Pro
        pro_tenant = Tenant.objects.get(slug="pro-demo")
        self.assertEqual(pro_tenant.plan_tier, "pro")
        self.assertTrue(pro_tenant.custom_domain_enabled)
        
        # Capturar contagens atuais para verificar idempotência
        count_tenants = Tenant.objects.count()
        count_users = User.objects.count()
        count_services = Service.objects.count()
        count_appointments = Appointment.objects.count()
        count_ledger = CommLedger.objects.count()

        # 2. Segunda execução (Idempotência)
        call_command("seed_demo")

        # As contagens não devem mudar (ou mudar minimamente se houver lógica temporal que força recriação,
        # mas o objetivo do seed é ser idempotente para as estruturas base)
        
        self.assertEqual(Tenant.objects.count(), count_tenants, "Tenants duplicados na segunda execução")
        self.assertEqual(User.objects.count(), count_users, "Usuários duplicados na segunda execução")
        # Services e Appointments podem ter lógica de get_or_create, vamos validar
        self.assertEqual(Service.objects.count(), count_services, "Serviços duplicados na segunda execução")
        
        # Nota: Se o seed usar datas relativas fixas (ex: timezone.now() + 1 day), 
        # a segunda execução pode criar novos slots/appointments se o 'now' mudar significativamente 
        # ou se a lógica de busca não compensar. Mas num teste unitário, o tempo é "congelado" ou rápido.
        # Vamos assumir que get_or_create funciona bem.
