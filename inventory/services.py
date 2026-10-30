"""Helpers reutilizáveis do módulo `inventory` para outros apps (ex.: `reports`).

BE-REPORTS-01 (#569): o relatório cruzado de faturamento (COGS/margem) e o
relatório de estoque isolado precisam saber se um tenant "tem estoque ativo"
antes de calcular/exibir essas seções.

Importante: `inventory` (BE-STOCK-01~04, #464-467) foi implementado **sem**
gate de plano — todos os tenants em plano ativo (Basic/Founder; Pro
bloqueado mas preservado) têm acesso igual ao CRUD de itens e movimentações,
ver docstrings em `inventory/models.py` e `inventory/views.py`. Não existe
nenhuma flag de plano ou addon específica para estoque em `Tenant`.

Por isso, "estoque ativo" aqui não é uma permissão de plano, e sim um sinal
de uso real da feature: o tenant já cadastrou pelo menos um `InventoryItem`.
Esse é o mesmo critério, na prática, que já deixa os relatórios/alertas de
estoque "vazios" para quem nunca usou o módulo (ver
`InventoryAlertListView`), então reaproveitamos a mesma ideia aqui em vez de
inventar uma nova gate de plano que não existe no restante do código.
"""

from __future__ import annotations

from typing import Optional

from inventory.models import InventoryItem


def tenant_has_active_stock(tenant: Optional[object]) -> bool:
    """Retorna True se o tenant já usa o módulo de estoque.

    "Usar" = ter pelo menos um `InventoryItem` cadastrado. Tenants que nunca
    criaram um item de estoque não devem ver seções de estoque/COGS/margem
    nos relatórios (nem erro, apenas ausência dos dados).
    """
    if tenant is None:
        return False
    return InventoryItem.objects.filter(tenant=tenant).exists()
