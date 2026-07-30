from django.db import models


class InventoryItem(models.Model):
    """Item de estoque de um tenant (ex.: luvas, tintas, agulhas).

    BE-STOCK-01 (#464): base para controle de materiais consumidos no dia a
    dia. Todos os tenants têm acesso igual, sem limite por plano — a
    diferenciação Basic/Founder/Pro prevista na issue original não se aplica
    mais (Pro está bloqueado/não vendável, ver `Tenant.BLOCKED_PLANS`).
    """

    tenant = models.ForeignKey(
        "users.Tenant",
        on_delete=models.CASCADE,
        related_name="inventory_items",
    )
    name = models.CharField(max_length=255)
    unit = models.CharField(
        max_length=50,
        help_text="Unidade de medida (ex.: unidade, cx, frasco).",
    )
    quantity = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("name",)
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "name"],
                name="inventory_item_unique_tenant_name",
            )
        ]
        indexes = [
            models.Index(fields=["tenant", "name"], name="inv_item_tenant_name_idx"),
        ]

    def __str__(self):
        return f"{self.name} ({self.tenant_id})"
