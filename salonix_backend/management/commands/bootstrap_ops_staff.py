from __future__ import annotations

import getpass
from typing import Any

from django.core.management.base import BaseCommand, CommandError

from users.models import CustomUser


class Command(BaseCommand):
    help = "Cria ou atualiza utilizadores staff do console Ops."

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--email",
            required=True,
            help="Email do utilizador Ops",
        )
        parser.add_argument(
            "--role",
            required=True,
            choices=CustomUser.OpsRoles.values,
            help="Role do utilizador (ops_admin ou ops_support)",
        )
        parser.add_argument(
            "--password",
            help="Senha inicial do utilizador (será solicitada se omitida)",
        )
        parser.add_argument(
            "--force",
            action="store_true",
            help="Atualiza o utilizador existente sobrescrevendo senha e role",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        email = options["email"].strip().lower()
        role = options["role"]
        password = options.get("password")
        force = options.get("force", False)

        if not password:
            password = getpass.getpass("Senha temporária para o utilizador Ops: ")
            if not password:
                raise CommandError("Senha não pode ser vazia.")

        username = self._build_username(email)

        user, created = CustomUser.objects.get_or_create(
            email=email,
            defaults={
                "username": username,
                "ops_role": role,
                "is_active": True,
            },
        )

        if created:
            self.stdout.write(self.style.SUCCESS("✅ Utilizador Ops criado."))
        else:
            if not force:
                raise CommandError(
                    "Utilizador já existe. Use --force para atualizar senha e role."
                )
            self.stdout.write(self.style.WARNING("⚠️ Utilizador existente será atualizado."))

        user.username = user.username or username
        user.ops_role = role
        user.is_active = True
        user._tenant_explicitly_none = True  # evitar associação automática em seeds de teste
        user.tenant = None
        user.set_password(password)
        user.save()

        self.stdout.write("")
        self.stdout.write("📋 Resumo:")
        self.stdout.write(f"   Email: {user.email}")
        self.stdout.write(f"   Username: {user.username}")
        self.stdout.write(f"   Role: {user.ops_role}")
        self.stdout.write(f"   Scope: {user.ops_role}")
        self.stdout.write("\n⚠️ Altere a senha após o primeiro login.")

    def _build_username(self, email: str) -> str:
        base_username = email.split("@")[0]
        candidate = base_username
        idx = 1
        while CustomUser.objects.filter(username=candidate).exists():
            idx += 1
            candidate = f"{base_username}{idx}"
        return candidate
