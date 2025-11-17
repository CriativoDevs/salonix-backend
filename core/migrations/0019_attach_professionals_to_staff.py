from django.db import migrations


def attach_professionals_to_staff(apps, schema_editor):
    Professional = apps.get_model("core", "Professional")
    TenantStaffMember = apps.get_model("users", "TenantStaffMember")

    logs: list[str] = []
    created_staff = 0
    updated_professionals = 0

    for professional in Professional.objects.select_related("tenant", "user").all():
        tenant = getattr(professional, "tenant", None)
        user = getattr(professional, "user", None)

        if tenant is None or user is None:
            logs.append(
                f"[WARN] professional_id={professional.id} missing tenant/user; skipped."
            )
            continue

        if professional.staff_member_id:
            staff = TenantStaffMember.objects.filter(
                id=professional.staff_member_id
            ).first()
            if staff is None:
                logs.append(
                    f"[WARN] professional_id={professional.id} staff_member_id={professional.staff_member_id} not found; attempting reassociation."
                )
            else:
                # Ensure integrity with tenant/user
                updated_fields = []
                if staff.tenant_id != tenant.id:
                    staff.tenant_id = tenant.id
                    updated_fields.append("tenant")
                if staff.user_id != user.id:
                    staff.user_id = user.id
                    updated_fields.append("user")
                if updated_fields:
                    staff.save(update_fields=updated_fields + ["updated_at"])
                continue
        else:
            staff = None

        if staff is None:
            staff = (
                TenantStaffMember.objects.filter(tenant=tenant, user=user)
                .order_by("id")
                .first()
            )

        if staff is None:
            role_collaborator = getattr(
                TenantStaffMember.Role, "COLLABORATOR", "collaborator"
            )
            status_active = getattr(TenantStaffMember.Status, "ACTIVE", "active")
            staff = TenantStaffMember.objects.create(
                tenant=tenant,
                user=user,
                role=role_collaborator,
                status=status_active,
            )
            created_staff += 1

        if professional.staff_member_id != staff.id:
            professional.staff_member_id = staff.id
            updated_professionals += 1
            professional.save(update_fields=["staff_member"])

    if logs:
        print("\n".join(logs))
    print(
        f"[INFO] Professionals linked to staff: {updated_professionals}; staff created: {created_staff}"
    )


class Migration(migrations.Migration):
    dependencies = [
        (
            "core",
            "0018_rename_core_prof_tenant_staff_idx_core_profes_tenant__f17964_idx",
        ),
        ("users", "0013_tenantstaffmember"),
    ]

    operations = [
        migrations.RunPython(attach_professionals_to_staff, migrations.RunPython.noop),
    ]
