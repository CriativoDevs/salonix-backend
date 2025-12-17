import pytest
from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth.models import Group, Permission
from users.models import CustomUser, Tenant
from core.models import (
    Appointment,
    AppointmentSeries,
    Professional,
    ScheduleSlot,
    Service,
)
from django.utils import timezone
from datetime import timedelta
from salonix_backend.admin_permissions import (
    setup_admin_permissions,
    create_admin_groups,
)


@pytest.mark.django_db
class TestDjangoAdmin:
    """Testes para funcionalidades do Django Admin."""

    def setup_method(self):
        """Configuração para cada teste."""
        self.client = Client()

        # Criar tenant de teste
        self.tenant = Tenant.objects.create(
            name="Salão Teste", slug="salao-teste", plan_tier="pro"
        )

        # Criar superusuário
        self.superuser = CustomUser.objects.create_superuser(
            username="admin",
            email="admin@test.com",
            password="admin123",
            tenant=self.tenant,
        )

        # Criar usuário staff
        self.staff_user = CustomUser.objects.create_user(
            username="staff",
            email="staff@test.com",
            password="staff123",
            tenant=self.tenant,
            is_staff=True,
        )

        # Configurar permissões
        setup_admin_permissions()
        create_admin_groups()

    def test_admin_login_superuser(self):
        """Testa login do superusuário no admin."""
        # Login
        login_success = self.client.login(username="admin", password="admin123")
        assert login_success

        # Acessar admin
        response = self.client.get("/admin/")
        assert response.status_code == 200
        assert "Salonix - Gestão de Salões" in response.content.decode()

    def test_admin_login_staff(self):
        """Testa login de usuário staff no admin."""
        # Login
        login_success = self.client.login(username="staff", password="staff123")
        assert login_success

        # Acessar admin
        response = self.client.get("/admin/")
        assert response.status_code == 200

    def test_admin_dashboard_stats(self):
        """Testa se o dashboard mostra estatísticas."""
        self.client.login(username="admin", password="admin123")

        response = self.client.get("/admin/")
        content = response.content.decode()

        # Verificar se estatísticas estão presentes
        assert "Dashboard TimelyOne" in content
        assert "Tenants Ativos" in content
        assert "Total Usuários" in content
        assert "Agendamentos Hoje" in content

    def test_tenant_admin_list(self):
        """Testa listagem de tenants no admin."""
        self.client.login(username="admin", password="admin123")

        response = self.client.get("/admin/users/tenant/")
        assert response.status_code == 200
        assert "Salão Teste" in response.content.decode()

    def test_tenant_admin_detail(self):
        """Testa visualização de detalhes do tenant."""
        self.client.login(username="admin", password="admin123")

        response = self.client.get(f"/admin/users/tenant/{self.tenant.pk}/change/")
        assert response.status_code == 200

        content = response.content.decode()
        assert self.tenant.name in content
        assert self.tenant.slug in content

    def test_staff_permissions_tenant_access(self):
        """Testa se staff só acessa dados do próprio tenant."""
        # Criar outro tenant
        other_tenant = Tenant.objects.create(name="Outro Salão", slug="outro-salao")

        # Criar usuário do outro tenant
        CustomUser.objects.create_user(
            username="other_staff",
            email="other@test.com",
            password="other123",
            tenant=other_tenant,
            is_staff=True,
        )

        # Login como staff do primeiro tenant
        self.client.login(username="staff", password="staff123")

        # Tentar acessar tenant do outro usuário
        response = self.client.get(f"/admin/users/tenant/{other_tenant.pk}/change/")
        # Staff não deveria ver outros tenants
        assert response.status_code in [403, 404]

    def test_admin_custom_actions(self):
        """Testa ações customizadas do admin."""
        self.client.login(username="admin", password="admin123")

        # Criar tenant inativo
        inactive_tenant = Tenant.objects.create(
            name="Salão Inativo", slug="salao-inativo", is_active=False
        )

        # Testar ação de ativar tenant
        response = self.client.post(
            "/admin/users/tenant/",
            {
                "action": "activate_tenants",
                "_selected_action": [inactive_tenant.pk],
            },
        )

        # Verificar se foi redirecionado (ação executada)
        assert response.status_code == 302

        # Verificar se tenant foi ativado
        inactive_tenant.refresh_from_db()
        assert inactive_tenant.is_active is True

    def test_admin_search_functionality(self):
        """Testa funcionalidade de busca no admin."""
        self.client.login(username="admin", password="admin123")

        # Buscar tenant por nome
        response = self.client.get("/admin/users/tenant/?q=Teste")
        assert response.status_code == 200
        assert "Salão Teste" in response.content.decode()

        # Buscar por slug
        response = self.client.get("/admin/users/tenant/?q=salao-teste")
        assert response.status_code == 200
        assert "Salão Teste" in response.content.decode()

    def test_admin_filters(self):
        """Testa filtros do admin."""
        self.client.login(username="admin", password="admin123")

        # Filtrar por plano
        response = self.client.get("/admin/users/tenant/?plan_tier=pro")
        assert response.status_code == 200
        assert "Salão Teste" in response.content.decode()

        # Filtrar por status ativo
        response = self.client.get("/admin/users/tenant/?is_active__exact=1")
        assert response.status_code == 200

    def test_user_admin_tenant_filter(self):
        """Testa se admin de usuários mostra filtro por tenant."""
        self.client.login(username="admin", password="admin123")

        response = self.client.get("/admin/users/customuser/")
        assert response.status_code == 200

        content = response.content.decode()
        assert "Salão Teste" in content  # Nome do tenant deve aparecer

    def test_appointment_series_admin_list_and_detail(self):
        """Testa listagem e detalhe de séries no admin."""
        self.client.login(username="admin", password="admin123")

        service = Service.objects.create(
            user=self.superuser,
            tenant=self.tenant,
            name="Corte",
            price_eur=25,
            duration_minutes=30,
        )
        professional = Professional.objects.create(
            user=self.superuser, tenant=self.tenant, name="Prof Test"
        )
        slot = ScheduleSlot.objects.create(
            tenant=self.tenant,
            professional=professional,
            start_time=timezone.now() + timedelta(days=1),
            end_time=timezone.now() + timedelta(days=1, minutes=30),
        )
        slot.mark_booked()

        series = AppointmentSeries.objects.create(
            tenant=self.tenant,
            client=self.superuser,
            service=service,
            professional=professional,
            notes="Série teste",
        )
        Appointment.objects.create(
            tenant=self.tenant,
            client=self.superuser,
            service=service,
            professional=professional,
            slot=slot,
            series=series,
        )

        list_url = reverse("salonix_admin:core_appointmentseries_changelist")
        list_response = self.client.get(list_url)
        assert list_response.status_code == 200
        assert f">{series.id}<" in list_response.content.decode()

        detail_url = reverse(
            "salonix_admin:core_appointmentseries_change", args=[series.pk]
        )
        detail = self.client.get(detail_url)
        assert detail.status_code == 200
        html = detail.content.decode()
        assert "Série teste" in html
        assert self.superuser.username in html
        assert professional.name in html

    def test_appointment_admin_series_filters(self):
        """Testa filtro por série em AppointmentAdmin."""
        self.client.login(username="admin", password="admin123")

        service = Service.objects.create(
            user=self.superuser,
            tenant=self.tenant,
            name="Spa",
            price_eur=50,
            duration_minutes=60,
        )
        professional = Professional.objects.create(
            user=self.superuser, tenant=self.tenant, name="Pro Spa"
        )
        slot = ScheduleSlot.objects.create(
            tenant=self.tenant,
            professional=professional,
            start_time=timezone.now() + timedelta(days=2),
            end_time=timezone.now() + timedelta(days=2, minutes=60),
        )
        slot.mark_booked()
        series = AppointmentSeries.objects.create(
            tenant=self.tenant,
            client=self.superuser,
            service=service,
            professional=professional,
        )
        Appointment.objects.create(
            tenant=self.tenant,
            client=self.superuser,
            service=service,
            professional=professional,
            slot=slot,
            series=series,
        )

        appointments_url = reverse("salonix_admin:core_appointment_changelist")
        response = self.client.get(f"{appointments_url}?series__id__exact={series.pk}")
        assert response.status_code == 200
        expected_link = reverse(
            "salonix_admin:core_appointmentseries_change", args=[series.pk]
        )
        assert expected_link in response.content.decode()


class TestAdminPermissions(TestCase):
    """Testes para permissões customizadas do admin."""

    def setUp(self):
        """Configuração para testes de permissões."""
        self.tenant = Tenant.objects.create(name="Salão Teste", slug="salao-teste")

        setup_admin_permissions()
        create_admin_groups()

    def test_custom_permissions_created(self):
        """Testa se permissões customizadas foram criadas."""
        expected_permissions = [
            "view_all_tenants",
            "manage_tenant_features",
            "view_system_stats",
            "manage_subscriptions",
        ]

        for codename in expected_permissions:
            assert Permission.objects.filter(codename=codename).exists()

    def test_admin_groups_created(self):
        """Testa se grupos administrativos foram criados."""
        expected_groups = ["Salonix Admins", "Tenant Managers", "Support"]

        for group_name in expected_groups:
            assert Group.objects.filter(name=group_name).exists()

    def test_admin_group_permissions(self):
        """Testa se grupos têm as permissões corretas."""
        admin_group = Group.objects.get(name="Salonix Admins")

        # Verificar se grupo admin tem permissões customizadas
        custom_perms = admin_group.permissions.filter(
            codename__in=[
                "view_all_tenants",
                "manage_tenant_features",
                "view_system_stats",
                "manage_subscriptions",
            ]
        )

        assert custom_perms.count() == 4

    def test_user_group_assignment(self):
        """Testa atribuição de usuários a grupos."""
        user = CustomUser.objects.create_user(
            username="test_admin",
            email="test@admin.com",
            password="test123",
            tenant=self.tenant,
        )

        # Adicionar ao grupo admin
        admin_group = Group.objects.get(name="Salonix Admins")
        user.groups.add(admin_group)

        assert user.groups.filter(name="Salonix Admins").exists()
        assert user.has_perm("users.view_all_tenants") or user.is_superuser


@pytest.mark.django_db
class TestAdminIntegration:
    """Testes de integração do admin com outros componentes."""

    def setup_method(self):
        """Configuração para testes de integração."""
        self.client = Client()

        self.tenant = Tenant.objects.create(
            name="Salão Integração",
            slug="salao-integracao",
            plan_tier="standard",
            reports_enabled=True,
        )

        self.superuser = CustomUser.objects.create_superuser(
            username="admin",
            email="admin@integration.com",
            password="admin123",
            tenant=self.tenant,
        )

    def test_admin_with_services(self):
        """Testa admin com serviços criados."""
        # Criar serviço
        Service.objects.create(
            tenant=self.tenant,
            user=self.superuser,
            name="Corte de Cabelo",
            price_eur=25.00,
            duration_minutes=30,
        )

        self.client.login(username="admin", password="admin123")

        # Acessar lista de serviços
        response = self.client.get("/admin/core/service/")
        assert response.status_code == 200
        assert "Corte de Cabelo" in response.content.decode()

    def test_admin_tenant_feature_summary(self):
        """Testa se resumo de features aparece no admin."""
        self.client.login(username="admin", password="admin123")

        response = self.client.get("/admin/users/tenant/")
        content = response.content.decode()

        # Verificar se features ativas aparecem
        assert "📊 Relatórios" in content  # Tenant tem reports_enabled=True

    def test_admin_links_between_models(self):
        """Testa links entre modelos no admin."""
        self.client.login(username="admin", password="admin123")

        # Acessar detalhes do tenant
        response = self.client.get(f"/admin/users/tenant/{self.tenant.pk}/change/")
        content = response.content.decode()

        # Verificar se há link para usuários do tenant
        assert "usuários" in content.lower()

    def test_admin_dashboard_with_data(self):
        """Testa dashboard com dados reais."""
        # Criar alguns dados
        Service.objects.create(
            tenant=self.tenant,
            user=self.superuser,
            name="Serviço Teste",
            price_eur=20.00,
            duration_minutes=45,
        )

        self.client.login(username="admin", password="admin123")

        response = self.client.get("/admin/")
        content = response.content.decode()

        # Verificar se estatísticas são atualizadas
        assert "1" in content  # Pelo menos 1 tenant ativo
        assert "Dashboard TimelyOne" in content
