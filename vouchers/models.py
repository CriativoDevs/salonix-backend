import secrets
import string

from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

CODE_ALPHABET = string.ascii_uppercase + string.digits
CODE_LENGTH = 8
_MAX_CODE_GENERATION_ATTEMPTS = 10


def generate_voucher_code() -> str:
    """Gera um código alfanumérico maiúsculo de 8 caracteres.

    Usa `secrets` (CSPRNG), não `random` — o código é exibido/comunicado ao
    cliente e, mesmo não sendo hoje usado como credencial de resgate (ver
    `Voucher.save`/apply-voucher, que usam `client_voucher_id` autenticado),
    é o tipo de campo que tende a virar ponto de resgate público no futuro.
    """

    return "".join(secrets.choice(CODE_ALPHABET) for _ in range(CODE_LENGTH))


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


class BirthdayVoucherConfig(models.Model):
    """Template (por tenant) do voucher automático de aniversário
    (BE-VOUCHER-05, #474).

    Cada tenant pode guardar até `MAX_TEMPLATES_PER_TENANT` templates
    (percentual/fixo/serviço grátis + validade), mas apenas **um** deles
    pode estar `is_selected=True` por vez — é esse que o job periódico
    `send_birthday_vouchers` usa para gerar os vouchers do dia. Os demais
    ficam guardados prontos para o tenant trocar depois.

    Decisão de design (2026-08, ajuste de escopo BE-VOUCHER-05): o campo
    `is_active` do desenho original (feature ligada/desligada a nível de
    tenant, separado de "qual template usar") foi **removido** em favor de
    só `is_selected` — nenhum template selecionado já significa "feature
    desligada" (comportamento padrão em tenant novo, sem precisar de um
    segundo flag para o mesmo conceito). `send_birthday_vouchers` passou a
    iterar `BirthdayVoucherConfig.objects.filter(is_selected=True)`.
    """

    MAX_TEMPLATES_PER_TENANT = 3

    tenant = models.ForeignKey(
        "users.Tenant",
        on_delete=models.CASCADE,
        related_name="birthday_voucher_configs",
    )
    voucher_type = models.CharField(
        max_length=20,
        choices=Voucher.VoucherType.choices,
        default=Voucher.VoucherType.PERCENT,
    )
    voucher_value = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        default=10,
        help_text="Percentual ou valor fixo. Não se aplica a 'free_service'.",
    )
    service = models.ForeignKey(
        "core.Service",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="birthday_voucher_configs",
        help_text="Obrigatório apenas quando voucher_type='free_service'.",
    )
    validity_days = models.PositiveIntegerField(
        default=30,
        help_text="Validade (em dias, a partir da geração) do voucher de aniversário criado.",
    )
    is_selected = models.BooleanField(
        default=False,
        help_text=(
            "Template usado pelo job de envio automático de vouchers de "
            "aniversário. No máximo 1 por tenant pode estar selecionado — "
            "nenhum selecionado equivale à feature desligada."
        ),
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-created_at",)

    def __str__(self):
        return f"BirthdayVoucherConfig({self.tenant_id}, selected={self.is_selected})"

    def clean(self):
        errors = {}
        if self.voucher_type == Voucher.VoucherType.FREE_SERVICE:
            if self.service_id is None:
                errors["service"] = "Obrigatório para vouchers do tipo 'free_service'."
        elif self.voucher_value is None:
            errors["voucher_value"] = (
                "Obrigatório para vouchers do tipo 'percent'/'fixed'."
            )

        if self.tenant_id is not None and self._state.adding:
            existing_count = BirthdayVoucherConfig.objects.filter(
                tenant_id=self.tenant_id
            ).count()
            if existing_count >= self.MAX_TEMPLATES_PER_TENANT:
                errors["__all__"] = (
                    "Cada tenant pode ter no máximo "
                    f"{self.MAX_TEMPLATES_PER_TENANT} templates de voucher "
                    "de aniversário."
                )

        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        if self.is_selected:
            # Seleção exclusiva por tenant: desmarcar os outros templates do
            # mesmo tenant em vez de validar/rejeitar — mais simples e menos
            # propenso a erro (nenhuma corrida entre "rejeitar 2º select" e
            # "trocar de template selecionado", que é o fluxo normal de uso).
            BirthdayVoucherConfig.objects.filter(
                tenant_id=self.tenant_id, is_selected=True
            ).exclude(pk=self.pk).update(is_selected=False)


class BirthdayVoucherLog(models.Model):
    """Marca que já processámos o voucher de aniversário de um cliente numa
    determinada data (BE-VOUCHER-05, #474).

    Garante idempotência do job periódico `send_birthday_vouchers`: a
    constraint única `(tenant, client, sent_date)` impede que uma segunda
    execução no mesmo dia gere um novo `Voucher`/`ClientVoucher` ou dispare
    outro e-mail para o mesmo cliente. Preferimos este registo explícito a
    tentar inferir "já processado" a partir de `ClientVoucher` (que não tem
    nenhuma marca de "gerado automaticamente por aniversário nesta data" e
    poderia colidir com vouchers atribuídos manualmente no mesmo dia).
    """

    tenant = models.ForeignKey(
        "users.Tenant",
        on_delete=models.CASCADE,
        related_name="birthday_voucher_logs",
    )
    client = models.ForeignKey(
        "core.SalonCustomer",
        on_delete=models.CASCADE,
        related_name="birthday_voucher_logs",
    )
    sent_date = models.DateField()
    client_voucher = models.ForeignKey(
        ClientVoucher,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="birthday_log_entries",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "client", "sent_date"],
                name="birthday_voucher_log_unique_tenant_client_date",
            )
        ]
        indexes = [
            models.Index(
                fields=["tenant", "sent_date"], name="birthday_log_tenant_date_idx"
            ),
        ]

    def __str__(self):
        return f"BirthdayVoucherLog({self.client_id}, {self.sent_date})"
