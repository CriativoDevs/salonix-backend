from django.core.management.base import BaseCommand
from django.contrib.auth.models import Group, Permission
from users.models import CustomUser
from salonix_backend.admin_permissions import (
    setup_admin_permissions,
    create_admin_groups,
)


class Command(BaseCommand):
    """
    Comando para configurar permissões e grupos do admin Django.

    Usage:
        python manage.py setup_admin
        python manage.py setup_admin --create-superuser
    """

    help = "Configura permissões e grupos para o Django Admin"

    def add_arguments(self, parser):
        parser.add_argument(
            "--create-superuser",
            action="store_true",
            help="Criar superusuário se não existir",
        )
        parser.add_argument(
            "--superuser-email",
            type=str,
            default="admin@salonix.pt",
            help="Email do superusuário (default: admin@salonix.pt)",
        )

    def handle(self, *args, **options):
        self.stdout.write(self.style.SUCCESS("🚀 Configurando Django Admin..."))

        # 1. Configurar permissões customizadas
        self.stdout.write("📋 Configurando permissões customizadas...")
        setup_admin_permissions()
        self.stdout.write(self.style.SUCCESS("✅ Permissões configuradas"))

        # 2. Criar grupos
        self.stdout.write("👥 Criando grupos de usuários...")
        create_admin_groups()
        self.stdout.write(self.style.SUCCESS("✅ Grupos criados"))

        # 3. Criar superusuário se solicitado
        if options["create_superuser"]:
            self._create_superuser(options["superuser_email"])

        # 4. Mostrar estatísticas
        self._show_stats()

        self.stdout.write(
            self.style.SUCCESS("\n🎉 Django Admin configurado com sucesso!")
        )

    def _create_superuser(self, email):
        """Cria superusuário se não existir."""
        if CustomUser.objects.filter(is_superuser=True).exists():
            self.stdout.write(
                self.style.WARNING("⚠️ Superusuário já existe, pulando...")
            )
            return

        self.stdout.write(f"👤 Criando superusuário: {email}")

        # Criar superuser
        superuser = CustomUser.objects.create_superuser(
            username="admin",
            email=email,
            password="admin123",  # Senha temporária
            salon_name="Salonix Admin",
        )

        # Adicionar ao grupo Salonix Admins
        admin_group = Group.objects.get(name="Salonix Admins")
        superuser.groups.add(admin_group)

        self.stdout.write(self.style.SUCCESS(f"✅ Superusuário criado: {email}"))
        self.stdout.write(
            self.style.WARNING("⚠️ Senha temporária: admin123 (altere imediatamente!)")
        )

    def _show_stats(self):
        """Mostra estatísticas do admin."""
        self.stdout.write("\n📊 Estatísticas do Admin:")

        # Usuários
        total_users = CustomUser.objects.count()
        superusers = CustomUser.objects.filter(is_superuser=True).count()
        staff_users = CustomUser.objects.filter(is_staff=True).count()

        self.stdout.write(f"👥 Total usuários: {total_users}")
        self.stdout.write(f"🔑 Superusuários: {superusers}")
        self.stdout.write(f"🛡️ Staff: {staff_users}")

        # Grupos
        groups = Group.objects.count()
        self.stdout.write(f"👥 Grupos: {groups}")

        # Permissões customizadas
        custom_perms = Permission.objects.filter(
            codename__in=[
                "view_all_tenants",
                "manage_tenant_features",
                "view_system_stats",
                "manage_subscriptions",
            ]
        ).count()
        self.stdout.write(f"🔐 Permissões customizadas: {custom_perms}")

        # URLs do admin
        self.stdout.write("\n🌐 URLs do Admin:")
        self.stdout.write("   http://localhost:8000/admin/ - Login")
        self.stdout.write("   http://localhost:8000/admin/dashboard/ - Dashboard")
