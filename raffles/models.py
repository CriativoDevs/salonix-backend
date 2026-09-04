from django.core.exceptions import ValidationError
from django.db import models

from vouchers.models import Voucher


class Raffle(models.Model):
    """Sorteio de um tenant, com prêmio entregue como voucher ao vencedor
    (BE-RAFFLE-01, #475).

    O prêmio é configurado com os mesmos campos de tipo/valor/serviço de
    `vouchers.Voucher` (reaproveitando `Voucher.VoucherType` em vez de
    duplicar o enum) — ao sortear (`draw`), esses dados são usados para
    criar um `Voucher` novo, atribuído ao vencedor via `ClientVoucher`
    (mesma lógica de `VoucherViewSet._assign_voucher_to_client`).

    `participants` é uma M2M para `core.SalonCustomer` (sempre do mesmo
    tenant do sorteio — validado na view via `add-participants`, nunca no
    model, mesmo padrão de `Voucher.service`/`ClientVoucher.client`).
    """

    class Status(models.TextChoices):
        DRAFT = "draft", "Rascunho"
        DRAWN = "drawn", "Sorteado"

    tenant = models.ForeignKey(
        "users.Tenant",
        on_delete=models.CASCADE,
        related_name="raffles",
    )
    name = models.CharField(max_length=120)
    prize_description = models.TextField(blank=True, default="")
    prize_voucher_type = models.CharField(
        max_length=20, choices=Voucher.VoucherType.choices
    )
    prize_value = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Percentual ou valor fixo. Não se aplica a 'free_service'.",
    )
    prize_service = models.ForeignKey(
        "core.Service",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="raffles",
        help_text="Obrigatório apenas quando prize_voucher_type='free_service'.",
    )
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.DRAFT
    )
    participants = models.ManyToManyField(
        "core.SalonCustomer",
        related_name="raffles",
        blank=True,
    )
    winner = models.ForeignKey(
        "core.SalonCustomer",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="won_raffles",
    )
    winner_voucher = models.ForeignKey(
        "vouchers.ClientVoucher",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="raffle",
    )
    drawn_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-created_at",)

    def __str__(self):
        return f"{self.name} ({self.tenant_id})"

    def clean(self):
        errors = {}
        if self.prize_voucher_type == Voucher.VoucherType.FREE_SERVICE:
            if self.prize_service_id is None:
                errors["prize_service"] = (
                    "Obrigatório para prêmios do tipo 'free_service'."
                )
        elif self.prize_value is None:
            errors["prize_value"] = (
                "Obrigatório para prêmios do tipo 'percent'/'fixed'."
            )
        if errors:
            raise ValidationError(errors)
