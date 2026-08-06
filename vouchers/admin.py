from django.contrib import admin

from vouchers.models import BirthdayVoucherConfig, BirthdayVoucherLog, ClientVoucher, Voucher


@admin.register(Voucher)
class VoucherAdmin(admin.ModelAdmin):
    """Admin (leitura de suporte/OPS) de vouchers (BE-VOUCHER-01, #470).

    CRUD completo é feito pelo tenant via API (`/api/vouchers/`); o admin
    serve para suporte/OPS conseguirem inspecionar/corrigir vouchers sem
    acesso a shell/DB.
    """

    list_display = (
        "code",
        "tenant",
        "type",
        "value",
        "service",
        "max_uses",
        "valid_until",
        "created_at",
    )
    list_filter = ("type",)
    search_fields = ("code", "tenant__name", "tenant__slug")
    readonly_fields = ("created_at",)


@admin.register(ClientVoucher)
class ClientVoucherAdmin(admin.ModelAdmin):
    """Admin (leitura de suporte/OPS) de atribuições de voucher a clientes
    (BE-VOUCHER-02, #471).
    """

    list_display = (
        "voucher",
        "client",
        "tenant",
        "status",
        "assigned_at",
        "used_at",
        "sent_at",
    )
    list_filter = ("tenant",)
    search_fields = (
        "voucher__code",
        "client__name",
        "client__email",
        "tenant__name",
        "tenant__slug",
    )
    readonly_fields = ("assigned_at", "sent_at")


@admin.register(BirthdayVoucherConfig)
class BirthdayVoucherConfigAdmin(admin.ModelAdmin):
    """Admin (leitura/suporte OPS) dos templates de voucher de aniversário
    por tenant (BE-VOUCHER-05, #474 — até
    `BirthdayVoucherConfig.MAX_TEMPLATES_PER_TENANT` por tenant, no máximo 1
    `is_selected=True`). Edição normal é feita pelo tenant via
    `/api/vouchers/birthday-configs/`; o admin serve para suporte/OPS
    inspecionar/corrigir sem acesso a shell/DB.
    """

    list_display = (
        "tenant",
        "is_selected",
        "voucher_type",
        "voucher_value",
        "validity_days",
        "updated_at",
    )
    list_filter = ("is_selected", "voucher_type")
    search_fields = ("tenant__name", "tenant__slug")
    readonly_fields = ("created_at", "updated_at")


@admin.register(BirthdayVoucherLog)
class BirthdayVoucherLogAdmin(admin.ModelAdmin):
    """Admin (leitura de suporte/OPS) do registo de idempotência do job de
    aniversário (BE-VOUCHER-05, #474).
    """

    list_display = ("tenant", "client", "sent_date", "client_voucher", "created_at")
    list_filter = ("tenant",)
    search_fields = ("client__name", "client__email", "tenant__name", "tenant__slug")
    readonly_fields = ("created_at",)
