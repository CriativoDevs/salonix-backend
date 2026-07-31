import random
import string

from django.core.exceptions import ValidationError
from django.db import models

CODE_ALPHABET = string.ascii_uppercase + string.digits
CODE_LENGTH = 8
_MAX_CODE_GENERATION_ATTEMPTS = 10


def generate_voucher_code() -> str:
    """Gera um código alfanumérico maiúsculo de 8 caracteres."""

    return "".join(random.choices(CODE_ALPHABET, k=CODE_LENGTH))


class Voucher(models.Model):
    """Voucher de um tenant, para oferecer aos seus clientes (BE-VOUCHER-01, #470).

    Pode ser um desconto percentual, um valor fixo, ou um serviço gratuito.
    Criado antecipadamente e atribuído/aplicado depois (ver BE-VOUCHER-02
    para atribuição a cliente via `ClientVoucher`, e BE-VOUCHER-03 para
    aplicação no agendamento — não implementados ainda).
    """

    class VoucherType(models.TextChoices):
        PERCENT = "percent", "Percentual"
        FIXED = "fixed", "Valor fixo"
        FREE_SERVICE = "free_service", "Serviço grátis"

    tenant = models.ForeignKey(
        "users.Tenant",
        on_delete=models.CASCADE,
        related_name="vouchers",
    )
    code = models.CharField(
        max_length=32,
        help_text="Único por tenant. Gerado automaticamente se omitido.",
    )
    type = models.CharField(max_length=20, choices=VoucherType.choices)
    value = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Percentual ou valor fixo. Não se aplica a 'free_service'.",
    )
    service = models.ForeignKey(
        "core.Service",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="vouchers",
        help_text="Obrigatório apenas para vouchers do tipo 'free_service'.",
    )
    max_uses = models.PositiveIntegerField(default=1)
    valid_until = models.DateField(null=True, blank=True)
    notes = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-created_at",)
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "code"],
                name="voucher_unique_tenant_code",
            )
        ]
        indexes = [
            models.Index(fields=["tenant", "code"], name="voucher_tenant_code_idx"),
        ]

    def __str__(self):
        return f"{self.code} ({self.tenant_id})"

    def clean(self):
        errors = {}
        if self.type == self.VoucherType.FREE_SERVICE:
            if self.service_id is None:
                errors["service"] = "Obrigatório para vouchers do tipo 'free_service'."
        elif self.value is None:
            errors["value"] = "Obrigatório para vouchers do tipo 'percent'/'fixed'."
        if errors:
            raise ValidationError(errors)

    def _generate_unique_code(self) -> str:
        for _ in range(_MAX_CODE_GENERATION_ATTEMPTS):
            candidate = generate_voucher_code()
            if not Voucher.objects.filter(
                tenant_id=self.tenant_id, code=candidate
            ).exists():
                return candidate
        raise ValidationError("Não foi possível gerar um código único de voucher.")

    def save(self, *args, **kwargs):
        if not self.code:
            self.code = self._generate_unique_code()
        else:
            self.code = self.code.strip().upper()
        super().save(*args, **kwargs)
