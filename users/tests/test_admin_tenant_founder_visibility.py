import pytest

from django.contrib import admin

from users.models import Tenant


@pytest.mark.django_db
class TestTenantAdminFounderVisibility:
    """is_founder ficava invisível no Django Admin: a listagem e o form só
    mostravam plan_tier, que é sempre "basic" para tenants Founder (Founder
    herda Basic + a flag is_founder). Sem a flag no admin não dava para
    distinguir um tenant Founder de um Basic comum."""

    def test_is_founder_in_list_display(self):
        tenant_admin = admin.site._registry[Tenant]

        assert "is_founder" in tenant_admin.list_display

    def test_is_founder_in_list_filter(self):
        tenant_admin = admin.site._registry[Tenant]

        assert "is_founder" in tenant_admin.list_filter

    def test_is_founder_in_fieldsets(self):
        tenant_admin = admin.site._registry[Tenant]

        fields_by_section = {
            section: fields_config["fields"]
            for section, fields_config in tenant_admin.fieldsets
        }

        assert "is_founder" in fields_by_section["Plano e Configurações"]
