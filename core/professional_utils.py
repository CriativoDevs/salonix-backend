"""
Helpers compartilhados para vincular Service <-> Professional.

BE-PROF-01: extraído de ProfessionalViewSet para ser reaproveitado também
no fluxo de registro de tenant (users/serializers.py), onde o owner solo
passa a nascer com um Professional próprio já vinculado a todos os
Services ativos do tenant.

Vive em `core` (não em `users`) porque `core` já depende de `users`
(Tenant, TenantStaffMember, etc.) — o inverso criaria import circular.
Quem precisar chamar isto a partir de `users` deve importar localmente,
dentro da função que usa (nunca no topo do módulo).
"""

import logging

from core.models import Professional, ProfessionalService, Service

logger = logging.getLogger(__name__)


def get_sole_active_professional(tenant) -> Professional | None:
    """
    Retorna o Professional do tenant quando ele tem exatamente 1 staff
    member ativo (cenário de owner solo) e esse staff possui um
    Professional associado. Retorna None caso contrário (0 ou 2+ staff
    ativos, ou staff solo ainda sem Professional).

    Extraído de ProfessionalViewSet._auto_link_services_if_sole_active_staff
    (BE-PROF-01) para ser reaproveitado também ao criar um Service novo
    (ServiceViewSet.perform_create), evitando duplicar a condição de
    "staff solo" em dois lugares.
    """
    from users.models import TenantStaffMember

    active_staff = list(
        TenantStaffMember.objects.filter(
            tenant=tenant, status=TenantStaffMember.Status.ACTIVE
        )
    )
    if len(active_staff) != 1:
        return None

    sole_staff = active_staff[0]
    return Professional.objects.filter(
        tenant=tenant, staff_member=sole_staff
    ).first()


def link_all_tenant_services_to_professional(*, tenant, professional: Professional) -> int:
    """
    Vincula `professional` a todos os Services do tenant via
    ProfessionalService, pulando serviços já vinculados (ignore_conflicts).

    Retorna a quantidade de vínculos que a chamada tentou criar (não
    necessariamente o número efetivamente inserido, já que
    ignore_conflicts silencia duplicados).
    """
    services = list(Service.objects.filter(tenant=tenant))
    if not services:
        return 0

    to_create = [
        ProfessionalService(
            tenant=tenant,
            professional=professional,
            service=service,
            is_active=True,
        )
        for service in services
    ]
    ProfessionalService.objects.bulk_create(to_create, ignore_conflicts=True)
    return len(to_create)
