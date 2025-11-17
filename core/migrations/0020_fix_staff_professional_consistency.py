from django.db import migrations


def fix_staff_professional_consistency(apps, schema_editor):
    """
    Corrige inconsistências entre Professional e TenantStaffMember após migração para novo fluxo.

    1. Garante que todos os colaboradores ativos tenham Professional associado
    2. Corrige vínculos inconsistentes entre Professional e TenantStaffMember
    3. Desativa Professionals de staff desativados
    """
    Professional = apps.get_model("core", "Professional")
    TenantStaffMember = apps.get_model("users", "TenantStaffMember")

    logs = []

    # 1. Encontrar colaboradores ativos sem Professional
    collaborators_without_professional = TenantStaffMember.objects.filter(
        role="collaborator", status="active", professionals__isnull=True
    ).select_related("user", "tenant")

    for staff in collaborators_without_professional:
        # Verificar se existe Professional órfão para este usuário/tenant
        orphan_professional = Professional.objects.filter(
            user=staff.user, tenant=staff.tenant, staff_member__isnull=True
        ).first()

        if orphan_professional:
            # Reassociar Professional órfão
            orphan_professional.staff_member = staff
            orphan_professional.is_active = True
            orphan_professional.save(update_fields=["staff_member", "is_active"])
            logs.append(
                f"Reassociado Professional {orphan_professional.id} ao staff {staff.id}"
            )
        else:
            # Criar novo Professional
            display_name = (
                staff.user.get_full_name()
                or staff.user.first_name
                or staff.user.username
                or (staff.user.email or "").split("@")[0]
                or "Professional"
            )

            professional = Professional.objects.create(
                tenant=staff.tenant,
                user=staff.user,
                staff_member=staff,
                name=display_name[:100],
                is_active=True,
            )
            logs.append(f"Criado Professional {professional.id} para staff {staff.id}")

    # 2. Corrigir Professionals com vínculos inconsistentes
    inconsistent_professionals = Professional.objects.select_related(
        "staff_member", "user", "tenant"
    ).exclude(staff_member__isnull=True)

    for professional in inconsistent_professionals:
        staff = professional.staff_member
        updates = []

        # Verificar consistência tenant
        if professional.tenant_id != staff.tenant_id:
            professional.tenant = staff.tenant
            updates.append("tenant")

        # Verificar consistência user
        if professional.user_id != staff.user_id:
            professional.user = staff.user
            updates.append("user")

        # Verificar status ativo baseado no staff
        expected_active = staff.status == "active"
        if professional.is_active != expected_active:
            professional.is_active = expected_active
            updates.append("is_active")

        if updates:
            professional.save(update_fields=updates)
            logs.append(
                f"Corrigido Professional {professional.id}: {', '.join(updates)}"
            )

    # 3. Desativar Professionals de staff desativados
    inactive_staff_professionals = Professional.objects.filter(
        staff_member__status__in=["disabled", "invited"], is_active=True
    )

    for professional in inactive_staff_professionals:
        professional.is_active = False
        professional.save(update_fields=["is_active"])
        logs.append(f"Desativado Professional {professional.id} (staff inativo)")

    # 4. Managers e Owners que foram promovidos a colaboradores
    manager_owner_collaborators = TenantStaffMember.objects.filter(
        role="collaborator", status="active"
    ).select_related("user", "tenant")

    for staff in manager_owner_collaborators:
        # Garantir que colaboradores tenham Professional ativo
        professional = Professional.objects.filter(staff_member=staff).first()
        if professional and not professional.is_active:
            professional.is_active = True
            professional.save(update_fields=["is_active"])
            logs.append(f"Reativado Professional {professional.id} para colaborador")

    print(f"Migração concluída. {len(logs)} correções aplicadas:")
    for log in logs[:10]:  # Mostrar apenas primeiros 10 logs
        print(f"  - {log}")
    if len(logs) > 10:
        print(f"  ... e mais {len(logs) - 10} correções")


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0019_attach_professionals_to_staff"),
        ("users", "0013_tenantstaffmember"),
    ]

    operations = [
        migrations.RunPython(
            fix_staff_professional_consistency,
            migrations.RunPython.noop,
        ),
    ]
