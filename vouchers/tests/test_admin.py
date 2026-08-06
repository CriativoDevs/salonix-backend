from django.contrib import admin

from salonix_backend.admin import admin_site
from vouchers.admin import VoucherAdmin
from vouchers.models import Voucher


def test_voucher_is_registered_in_default_admin_site():
    assert admin.site.is_registered(Voucher)


def test_voucher_is_registered_in_custom_admin_site():
    """O painel real usado em produção é o `TimelyOneAdminSite` customizado
    (ver `salonix_backend/admin.py`), não o `admin.site` padrão do Django.
    """
    assert Voucher in admin_site._registry
    assert isinstance(admin_site._registry[Voucher], VoucherAdmin)


def test_admin_exposes_expected_list_display():
    model_admin = admin.site._registry[Voucher]
    assert isinstance(model_admin, VoucherAdmin)
    assert "tenant" in model_admin.list_display
    assert "code" in model_admin.list_display
    assert "type" in model_admin.list_display


def test_birthday_voucher_config_is_registered_in_custom_admin_site():
    from vouchers.admin import BirthdayVoucherConfigAdmin
    from vouchers.models import BirthdayVoucherConfig

    assert BirthdayVoucherConfig in admin_site._registry
    assert isinstance(
        admin_site._registry[BirthdayVoucherConfig], BirthdayVoucherConfigAdmin
    )


def test_birthday_voucher_log_is_registered_in_custom_admin_site():
    from vouchers.admin import BirthdayVoucherLogAdmin
    from vouchers.models import BirthdayVoucherLog

    assert BirthdayVoucherLog in admin_site._registry
    assert isinstance(
        admin_site._registry[BirthdayVoucherLog], BirthdayVoucherLogAdmin
    )
