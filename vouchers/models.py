import random
import string

from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

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


class ClientVoucher(models.Model):
    """Atribuição de um `Voucher` a um cliente do tenant (BE-VOUCHER-02, #471).

    `tenant` é redundante com `voucher.tenant`/`client.tenant` (ambos sempre
    coincidem — validado na view), mas é mantido explicitamente para permitir
    isolamento/index direto por tenant, seguindo o mesmo padrão usado em
    `core.models.Appointment`.
    """

    class Status(models.TextChoices):
        ACTIVE = "active", "Ativo"
        USED = "used", "Usado"
        EXPIRED = "expired", "Expirado"

    tenant = models.ForeignKey(
        "users.Tenant",
        on_delete=models.CASCADE,
        related_name="client_vouchers",
    )
    voucher = models.ForeignKey(
        Voucher,
        on_delete=models.CASCADE,
        related_name="client_vouchers",
    )
    client = models.ForeignKey(
        "core.SalonCustomer",
        on_delete=models.CASCADE,
        related_name="vouchers",
    )
    assigned_at = models.DateTimeField(auto_now_add=True)
    used_at = models.DateTimeField(null=True, blank=True)
    sent_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text=(
            "Última vez que o voucher foi enviado por e-mail ao cliente "
            "(BE-VOUCHER-04, #473). Reenvios deliberados atualizam este "
            "campo novamente — não é usado para bloquear reenvio, apenas "
            "para auditoria/evitar disparos acidentais duplicados."
        ),
    )
    used_in_booking = models.ForeignKey(
        "core.Appointment",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="vouchers_used",
    )

    class Meta:
        ordering = ("-assigned_at",)
        constraints = [
            models.UniqueConstraint(
                fields=["voucher", "client"],
                name="client_voucher_unique_voucher_client",
            )
        ]
        indexes = [
            models.Index(fields=["tenant", "client"], name="clientvoucher_tenant_cli_idx"),
        ]

    def __str__(self):
        return f"{self.voucher.code} -> {self.client_id}"

    @property
    def status(self) -> str:
        if self.used_at is not None:
            return self.Status.USED
        valid_until = self.voucher.valid_until
        if valid_until is not None and valid_until < timezone.localdate():
            return self.Status.EXPIRED
        return self.Status.ACTIVE
