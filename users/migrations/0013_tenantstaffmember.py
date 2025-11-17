from django.conf import settings
from django.db import migrations, models
from django.utils import timezone


def bootstrap_staff_members(apps, schema_editor):
    CustomUser = apps.get_model("users", "CustomUser")
    TenantStaffMember = apps.get_model("users", "TenantStaffMember")

    tenants_users = {}
    for user in CustomUser.objects.filter(tenant__isnull=False).order_by(
        "date_joined", "id"
    ):
        tenants_users.setdefault(user.tenant_id, []).append(user)

    for tenant_id, users in tenants_users.items():
        for index, user in enumerate(users):
            role = "owner" if index == 0 else "manager"
            TenantStaffMember.objects.create(
                tenant_id=tenant_id,
                user_id=user.id,
                role=role,
                status="active",
                activated_at=user.date_joined or timezone.now(),
            )


class Migration(migrations.Migration):
    dependencies = [
        ("users", "0012_tenant_auto_invite"),
    ]

    operations = [
        migrations.CreateModel(
            name="TenantStaffMember",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "role",
                    models.CharField(
                        choices=[
                            ("owner", "Owner"),
                            ("manager", "Manager"),
                            ("collaborator", "Collaborator"),
                        ],
                        default="collaborator",
                        help_text="Perfil de permissão dentro do tenant.",
                        max_length=20,
                    ),
                ),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("active", "Active"),
                            ("invited", "Invited"),
                            ("disabled", "Disabled"),
                        ],
                        default="active",
                        help_text="Estado atual do membro de equipe.",
                        max_length=20,
                    ),
                ),
                (
                    "invite_token",
                    models.CharField(
                        blank=True,
                        help_text="Token de convite pendente.",
                        max_length=128,
                        null=True,
                    ),
                ),
                (
                    "invite_token_expires_at",
                    models.DateTimeField(blank=True, null=True),
                ),
                ("invited_at", models.DateTimeField(blank=True, null=True)),
                ("activated_at", models.DateTimeField(blank=True, null=True)),
                ("deactivated_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "invited_by",
                    models.ForeignKey(
                        blank=True,
                        help_text="Usuário responsável pelo convite (quando aplicável).",
                        null=True,
                        on_delete=models.SET_NULL,
                        related_name="staff_invited",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "tenant",
                    models.ForeignKey(
                        help_text="Tenant ao qual o membro de equipe pertence.",
                        on_delete=models.CASCADE,
                        related_name="staff_members",
                        to="users.tenant",
                    ),
                ),
                (
                    "user",
                    models.OneToOneField(
                        on_delete=models.CASCADE,
                        related_name="staff_member",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "indexes": [
                    models.Index(fields=["tenant"], name="users_staff_tenant_idx"),
                    models.Index(
                        fields=["tenant", "role"], name="users_staff_tenant_role_idx"
                    ),
                    models.Index(
                        fields=["tenant", "status"],
                        name="users_staff_tenant_status_idx",
                    ),
                ],
            },
        ),
        migrations.AddConstraint(
            model_name="tenantstaffmember",
            constraint=models.UniqueConstraint(
                condition=models.Q(role="owner"),
                fields=("tenant",),
                name="unique_staff_owner_per_tenant",
            ),
        ),
        migrations.RunPython(bootstrap_staff_members, migrations.RunPython.noop),
    ]
