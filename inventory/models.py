from django.core.exceptions import ValidationError
from django.db import models, transaction


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
    minimum_quantity = models.PositiveIntegerField(
        default=0,
        null=True,
        blank=True,
        help_text=(
            "Estoque mínimo desejado. Usado pelo endpoint de alertas "
            "(BE-STOCK-04, #467): um item só entra em alerta quando este "
            "valor está definido (não nulo) e maior que zero, e a "
            "quantidade atual está no mínimo ou abaixo dele."
        ),
    )
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


class StockMovement(models.Model):
    """Movimentação (entrada/saída) de um `InventoryItem` (BE-STOCK-03, #466).

    Log imutável: uma vez criada, uma movimentação não é editada nem
    apagada via API — apenas listada e criada. Ao ser criada, atualiza
    automaticamente `InventoryItem.quantity` (soma para entrada, subtrai
    para saída). Disponível para todos os tenants, sem gate de plano —
    decisão de escopo revisada em relação à issue original (que previa
    exclusividade do plano Pro, hoje bloqueado/não vendável).
    """

    class MovementType(models.TextChoices):
        IN = "in", "Entrada"
        OUT = "out", "Saída"

    tenant = models.ForeignKey(
        "users.Tenant",
        on_delete=models.CASCADE,
        related_name="stock_movements",
    )
    item = models.ForeignKey(
        InventoryItem,
        on_delete=models.CASCADE,
        related_name="movements",
    )
    movement_type = models.CharField(max_length=3, choices=MovementType.choices)
    quantity = models.PositiveIntegerField()
    notes = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-created_at",)
        indexes = [
            models.Index(
                fields=["tenant", "item", "created_at"],
                name="stock_move_tenant_item_idx",
            ),
        ]

    def __str__(self):
        return f"{self.get_movement_type_display()} {self.quantity} - {self.item.name}"

    def save(self, *args, **kwargs):
        # Só aplica o ajuste de saldo na criação — o histórico é imutável,
        # então não há caminho de update que deva reajustar a quantidade.
        is_new = self._state.adding
        if not is_new:
            super().save(*args, **kwargs)
            return

        with transaction.atomic():
            item = InventoryItem.objects.select_for_update().get(pk=self.item_id)

            if self.movement_type == self.MovementType.OUT:
                new_quantity = item.quantity - self.quantity
                if new_quantity < 0:
                    raise ValidationError(
                        "Saída não pode deixar a quantidade do item negativa."
                    )
            else:
                new_quantity = item.quantity + self.quantity

            super().save(*args, **kwargs)

            item.quantity = new_quantity
            item.save(update_fields=["quantity", "updated_at"])
