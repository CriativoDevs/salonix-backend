"""Helpers compartilhados pelos testes (BE-SEC-01).

Rotas de staff exigem TenantStaffMember ATIVO no tenant do usuario
(core.permissions.IsTenantStaff). Usuarios criados direto com
CustomUser.objects.create_user nao tem esse vinculo; use ensure_staff().
"""


def ensure_staff(user, role="owner", tenant=None):
    """Garante um TenantStaffMember ATIVO para `user` e devolve o mesmo user.

    Idempotente: se o vinculo ja existe, nao altera (preserva role/status
    definidos pelo teste). Sem tenant resolvivel, nao faz nada.
    """
    from users.models import TenantStaffMember

    if user is None:
        return user
    tenant = tenant or getattr(user, "tenant", None)
    if tenant is None:
        return user
    if TenantStaffMember.objects.filter(user=user).exists():
        return user
    TenantStaffMember.objects.create(
        tenant=tenant,
        user=user,
        role=role,
        status=TenantStaffMember.Status.ACTIVE,
    )
    # invalida caches de role no objeto em memoria
    for attr in ("_staff_cache", "staff_member"):
        user.__dict__.pop(attr, None)
    return user
