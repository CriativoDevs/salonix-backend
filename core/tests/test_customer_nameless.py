"""
BE-CUSTOMER-NAMELESS-01: cliente sem contato quando business_type=Psicologia.
"""

import pytest
from rest_framework import status
from rest_framework.test import APIClient

from users.models import Tenant, CustomUser, TenantStaffMember


@pytest.mark.django_db
class TestCustomerNamelessCreation:

    def setup_method(self):
        self.client = APIClient()

    def _make_tenant(self, business_type, slug):
        return Tenant.objects.create(
            name=f"Tenant {slug}",
            slug=slug,
            business_type=business_type,
        )

    def _make_owner(self, tenant, username):
        user = CustomUser.objects.create_user(
            username=username,
            email=f"{username}@test.com",
            password="testpass123",
            tenant=tenant,
        )
        TenantStaffMember.objects.create(
            tenant=tenant, user=user, role=TenantStaffMember.Role.OWNER,
        )
        return user

    def test_psychology_tenant_can_create_customer_name_only(self):
        """Psicologia: criar cliente só com nome, sem email/telefone."""
        tenant = self._make_tenant(Tenant.BUSINESS_TYPE_PSYCHOLOGY, "psico")
        user = self._make_owner(tenant, "psico_owner")

        self.client.force_authenticate(user=user)
        response = self.client.post(
            "/api/salon/customers/",
            {"name": "Paciente Anônimo"},
            format="json",
        )

        assert response.status_code == status.HTTP_201_CREATED
        assert response.data["name"] == "Paciente Anônimo"
        assert response.data["email"] is None or response.data["email"] == ""
        assert response.data["phone_number"] is None or response.data["phone_number"] == ""

    def test_psychology_tenant_can_create_customer_with_contact(self):
        """Psicologia: criar cliente com contato funciona normalmente."""
        tenant = self._make_tenant(Tenant.BUSINESS_TYPE_PSYCHOLOGY, "psico2")
        user = self._make_owner(tenant, "psico2_owner")

        self.client.force_authenticate(user=user)
        response = self.client.post(
            "/api/salon/customers/",
            {"name": "Paciente Normal", "email": "paciente@email.com"},
            format="json",
        )

        assert response.status_code == status.HTTP_201_CREATED
        assert response.data["email"] == "paciente@email.com"

    def test_salon_tenant_cannot_create_customer_name_only(self):
        """Salão: criação sem email/telefone continua bloqueada."""
        tenant = self._make_tenant(Tenant.BUSINESS_TYPE_SALON, "salon1")
        user = self._make_owner(tenant, "salon_owner")

        self.client.force_authenticate(user=user)
        response = self.client.post(
            "/api/salon/customers/",
            {"name": "Cliente Sem Contato"},
            format="json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_other_tenant_cannot_create_customer_name_only(self):
        """Outro tipo: criação sem email/telefone continua bloqueada."""
        tenant = self._make_tenant(Tenant.BUSINESS_TYPE_OTHER, "other1")
        user = self._make_owner(tenant, "other_owner")

        self.client.force_authenticate(user=user)
        response = self.client.post(
            "/api/salon/customers/",
            {"name": "Cliente Sem Contato"},
            format="json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_psychology_tenant_edit_can_remove_all_contact(self):
        """Psicologia: editar cliente removendo email/telefone permitido."""
        tenant = self._make_tenant(Tenant.BUSINESS_TYPE_PSYCHOLOGY, "psico3")
        user = self._make_owner(tenant, "psico3_owner")

        self.client.force_authenticate(user=user)
        create_resp = self.client.post(
            "/api/salon/customers/",
            {"name": "Paciente X", "email": "x@email.com"},
            format="json",
        )
        assert create_resp.status_code == status.HTTP_201_CREATED
        customer_id = create_resp.data["id"]

        update_resp = self.client.patch(
            f"/api/salon/customers/{customer_id}/",
            {"email": "", "phone_number": ""},
            format="json",
        )
        assert update_resp.status_code == status.HTTP_200_OK

    def test_salon_tenant_edit_cannot_remove_all_contact(self):
        """Salão: editar cliente removendo todo contato continua bloqueado."""
        tenant = self._make_tenant(Tenant.BUSINESS_TYPE_SALON, "salon2")
        user = self._make_owner(tenant, "salon2_owner")

        self.client.force_authenticate(user=user)
        create_resp = self.client.post(
            "/api/salon/customers/",
            {"name": "Cliente Y", "email": "y@email.com"},
            format="json",
        )
        assert create_resp.status_code == status.HTTP_201_CREATED
        customer_id = create_resp.data["id"]

        update_resp = self.client.patch(
            f"/api/salon/customers/{customer_id}/",
            {"email": "", "phone_number": ""},
            format="json",
        )
        assert update_resp.status_code == status.HTTP_400_BAD_REQUEST
