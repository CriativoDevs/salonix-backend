"""
Celery tasks para o sistema de cancelamento de contas (BE-ACCOUNT-CANCEL #396).

Tasks principais:
- check_expired_cancellations: Verifica cancelamentos expirados e dispara hard delete
- hard_delete_tenant: Remove definitivamente um tenant após criar backup
- create_tenant_backup: Cria backup JSON com todos os dados do tenant
"""

import json
import logging
from datetime import datetime
from pathlib import Path

from celery import shared_task
from django.conf import settings
from django.core.serializers import serialize
from django.db import transaction
from django.utils import timezone

from users.models import Tenant

logger = logging.getLogger(__name__)


@shared_task(name="core.check_expired_cancellations")
def check_expired_cancellations():
    """
    Task agendada (cron diário 3:00 AM).

    Busca todos os tenants com status='cancelled' e scheduled_deletion_at <= now(),
    e dispara a task de hard delete para cada um.

    Returns:
        dict: Estatísticas de execução (tenants encontrados, deletados, erros)
    """
    logger.info("[CHECK_EXPIRED] Iniciando verificação de cancelamentos expirados")

    now = timezone.now()
    expired_tenants = Tenant.objects.filter(
        status=Tenant.STATUS_CANCELLED,
        scheduled_deletion_at__lte=now,
    )

    count = expired_tenants.count()
    logger.info(f"[CHECK_EXPIRED] Encontrados {count} tenants expirados")

    deleted = 0
    errors = 0

    for tenant in expired_tenants:
        try:
            logger.info(
                f"[CHECK_EXPIRED] Disparando hard delete para tenant_id={tenant.id} "
                f"slug={tenant.slug}"
            )
            # Dispara task assíncrona
            hard_delete_tenant.delay(tenant.id)
            deleted += 1
        except Exception as e:
            logger.error(
                f"[CHECK_EXPIRED] Erro ao disparar delete de tenant_id={tenant.id}: {e}",
                exc_info=True,
            )
            errors += 1

    result = {
        "checked_at": now.isoformat(),
        "found": count,
        "dispatched": deleted,
        "errors": errors,
    }

    logger.info(f"[CHECK_EXPIRED] Finalizado: {result}")
    return result


@shared_task(name="core.hard_delete_tenant", bind=True)
def hard_delete_tenant(self, tenant_id: int):
    """
    Remove definitivamente um tenant do banco de dados.

    Fluxo:
    1. Valida que o tenant existe e está com status='cancelled'
    2. Cria backup JSON completo dos dados
    3. Salva backup localmente (BACKUP_ROOT)
    4. Remove tenant (cascade delete automático pelo Django)
    5. Registra log de auditoria

    Args:
        tenant_id: ID do tenant a ser deletado

    Returns:
        dict: Resultado da operação (sucesso, backup_path, deleted_at)

    Raises:
        ValueError: Se tenant não existe ou status inválido
        Exception: Erros durante backup ou deleção
    """
    logger.info(f"[HARD_DELETE] Iniciando hard delete de tenant_id={tenant_id}")

    try:
        tenant = Tenant.objects.get(id=tenant_id)
    except Tenant.DoesNotExist:
        error = f"Tenant {tenant_id} não encontrado"
        logger.error(f"[HARD_DELETE] {error}")
        raise ValueError(error)

    # Validação de segurança: só deleta se status for 'cancelled'
    if tenant.status != Tenant.STATUS_CANCELLED:
        error = (
            f"Tenant {tenant_id} não pode ser deletado: "
            f"status atual é '{tenant.status}' (esperado: 'cancelled')"
        )
        logger.error(f"[HARD_DELETE] {error}")
        raise ValueError(error)

    # Validação: período de retenção expirado
    now = timezone.now()
    if tenant.can_reactivate():
        error = (
            f"Tenant {tenant_id} ainda pode ser reativado: "
            f"scheduled_deletion_at={tenant.scheduled_deletion_at} > now={now}"
        )
        logger.warning(f"[HARD_DELETE] {error}")
        raise ValueError(error)

    slug = tenant.slug

    try:
        # 1. Criar backup
        logger.info(
            f"[HARD_DELETE] Criando backup de tenant_id={tenant_id} slug={slug}"
        )
        backup_data = create_tenant_backup(tenant)

        # 2. Salvar backup localmente
        backup_path = save_backup_locally(tenant, backup_data)
        logger.info(f"[HARD_DELETE] Backup salvo: {backup_path}")

        # 3. Hard delete (cascade delete automático)
        with transaction.atomic():
            # Marca como 'deleted' antes de deletar (histórico)
            tenant.status = Tenant.STATUS_DELETED
            tenant.save(update_fields=["status"])

            logger.warning(
                f"[HARD_DELETE] DELETANDO tenant_id={tenant_id} slug={slug} "
                f"do banco de dados (IRREVERSÍVEL)"
            )
            tenant.delete()

        deleted_at = timezone.now()
        result = {
            "success": True,
            "tenant_id": tenant_id,
            "tenant_slug": slug,
            "backup_path": str(backup_path),
            "deleted_at": deleted_at.isoformat(),
        }

        logger.info(f"[HARD_DELETE] ✅ Sucesso: {result}")
        return result

    except Exception as e:
        logger.error(
            f"[HARD_DELETE] ❌ Erro ao deletar tenant_id={tenant_id}: {e}",
            exc_info=True,
        )
        raise


def create_tenant_backup(tenant: Tenant) -> dict:
    """
    Cria um backup completo dos dados de um tenant em formato JSON.

    Serializa:
    - Tenant (dados principais)
    - Users (CustomUser)
    - TenantStaffMembers

    Args:
        tenant: Instância do Tenant a ser backupeado

    Returns:
        dict: Estrutura JSON com metadados e dados serializados
    """
    from users.models import CustomUser, TenantStaffMember

    logger.info(f"[BACKUP] Criando backup de tenant_id={tenant.id} slug={tenant.slug}")

    backup = {
        "metadata": {
            "tenant_id": tenant.id,
            "tenant_slug": tenant.slug,
            "tenant_name": tenant.name,
            "plan_tier": tenant.plan_tier,
            "status": tenant.status,
            "cancelled_at": (
                tenant.cancelled_at.isoformat() if tenant.cancelled_at else None
            ),
            "scheduled_deletion_at": (
                tenant.scheduled_deletion_at.isoformat()
                if tenant.scheduled_deletion_at
                else None
            ),
            "backup_created_at": timezone.now().isoformat(),
            "backup_version": "1.0",
        },
        "data": {},
    }

    # Serializa apenas modelos essenciais
    models_to_backup = [
        ("tenant", [tenant]),
        ("users", CustomUser.objects.filter(tenant=tenant)),
        ("staff_members", TenantStaffMember.objects.filter(tenant=tenant)),
    ]

    for model_name, queryset in models_to_backup:
        try:
            if not hasattr(queryset, "__iter__"):
                queryset = [queryset]

            serialized = serialize("json", queryset)
            backup["data"][model_name] = json.loads(serialized)
            count = len(backup["data"][model_name])
            logger.info(f"[BACKUP] - {model_name}: {count} registros")
        except Exception as e:
            logger.warning(f"[BACKUP] Erro ao serializar {model_name}: {e}")
            backup["data"][model_name] = []

    logger.info(f"[BACKUP] Backup criado com sucesso: {len(backup['data'])} modelos")
    return backup


def save_backup_locally(tenant: Tenant, backup_data: dict) -> Path:
    """
    Salva o backup JSON no sistema de arquivos local.

    Estrutura:
    BACKUP_ROOT/tenants/{slug}/backup_{timestamp}.json

    Args:
        tenant: Instância do Tenant
        backup_data: Dados do backup

    Returns:
        Path: Caminho do arquivo salvo
    """
    backup_root = settings.BACKUP_ROOT
    tenant_dir = backup_root / "tenants" / tenant.slug

    # Cria diretórios se não existirem
    tenant_dir.mkdir(parents=True, exist_ok=True)

    # Nome do arquivo: backup_2026-02-05T15-30-45.json
    timestamp = datetime.now().strftime("%Y-%m-%dT%H-%M-%S")
    backup_filename = f"backup_{timestamp}.json"
    backup_path = tenant_dir / backup_filename

    logger.info(f"[BACKUP] Salvando backup em: {backup_path}")

    # Escreve JSON com indentação
    with open(backup_path, "w", encoding="utf-8") as f:
        json.dump(backup_data, f, ensure_ascii=False, indent=2)

    file_size = backup_path.stat().st_size
    logger.info(f"[BACKUP] ✅ Backup salvo: {backup_path} ({file_size} bytes)")

    return backup_path


@shared_task(name="core.send_deletion_reminders")
def send_deletion_reminders():
    """
    Task agendada (cron diário 9:00 AM).

    Envia lembretes para tenants que serão deletados em 7 dias.
    Notifica os owners sobre a exclusão iminente.

    Returns:
        dict: Estatísticas de envio (encontrados, enviados, erros)
    """
    from datetime import timedelta
    from core.email_utils import send_deletion_reminder_email
    from users.models import CustomUser

    logger.info("[DELETION_REMINDERS] Iniciando envio de lembretes")

    now = timezone.now()
    reminder_date = now + timedelta(days=7)

    # Buscar tenants que serão deletados em ~7 dias (±6 horas de margem)
    start_window = reminder_date - timedelta(hours=6)
    end_window = reminder_date + timedelta(hours=6)

    tenants_to_remind = Tenant.objects.filter(
        status=Tenant.STATUS_CANCELLED,
        scheduled_deletion_at__gte=start_window,
        scheduled_deletion_at__lte=end_window,
    )

    count = tenants_to_remind.count()
    logger.info(f"[DELETION_REMINDERS] Encontrados {count} tenants para lembrete")

    sent = 0
    errors = 0

    for tenant in tenants_to_remind:
        try:
            # Buscar owner do tenant via TenantStaffMember
            from users.models import TenantStaffMember

            staff_member = (
                TenantStaffMember.objects.filter(
                    tenant=tenant, role=TenantStaffMember.Role.OWNER
                )
                .select_related("user")
                .first()
            )

            if not staff_member:
                logger.warning(
                    f"[DELETION_REMINDERS] Tenant {tenant.id} não tem owner. Pulando."
                )
                continue

            owner = staff_member.user

            # Construir URL de reativação
            reactivation_url = f"{settings.FRONTEND_URL}/reativar/{tenant.id}/{tenant.reactivation_token}/"

            # Calcular dias restantes
            days_remaining = (tenant.scheduled_deletion_at - now).days

            # Enviar email
            send_deletion_reminder_email(
                tenant=tenant,
                owner_user=owner,
                reactivation_url=reactivation_url,
                days_remaining=max(1, days_remaining),  # Mínimo 1 dia
            )

            sent += 1
            logger.info(
                f"[DELETION_REMINDERS] ✅ Lembrete enviado para tenant {tenant.id} "
                f"({owner.email})"
            )

        except Exception as e:
            errors += 1
            logger.error(
                f"[DELETION_REMINDERS] ❌ Erro ao enviar lembrete para tenant {tenant.id}: {e}",
                exc_info=True,
            )

    result = {
        "checked_at": now.isoformat(),
        "found": count,
        "sent": sent,
        "errors": errors,
    }

    logger.info(f"[DELETION_REMINDERS] Finalizado: {result}")
    return result
