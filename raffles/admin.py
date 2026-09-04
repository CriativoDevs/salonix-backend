from django.contrib import admin

from raffles.models import Raffle


@admin.register(Raffle)
class RaffleAdmin(admin.ModelAdmin):
    """Admin (leitura de suporte/OPS) de sorteios (BE-RAFFLE-01, #475).

    CRUD completo é feito pelo tenant via API (`/api/raffles/`); o admin
    serve para suporte/OPS conseguirem inspecionar/corrigir sorteios sem
    acesso a shell/DB.
    """

    list_display = (
        "name",
        "tenant",
        "status",
        "prize_voucher_type",
        "winner",
        "drawn_at",
        "created_at",
    )
    list_filter = ("status", "prize_voucher_type")
    search_fields = ("name", "tenant__name", "tenant__slug")
    readonly_fields = ("created_at",)
