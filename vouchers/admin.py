from django.contrib import admin

from vouchers.models import Voucher


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
