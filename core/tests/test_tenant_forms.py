"""
BE-ANAMNESE-01: formulário customizável por tenant (anamnese genérica).
"""

import pytest
from rest_framework import status
from rest_framework.test import APIClient

from users.models import Tenant, CustomUser, TenantStaffMember
from core.models import SalonCustomer, TenantForm, TenantFormField, CustomerFormResponse


@pytest.mark.django_db
class TestTenantFormCRUD:

    def setup_method(self):
        self.client = APIClient()
        self.tenant = Tenant.objects.create(name="Tattoo Studio", slug="tattoo-studio")
        self.user = CustomUser.objects.create_user(
            username="owner", email="owner@tattoo.com", password="test123",
            tenant=self.tenant,
        )
        TenantStaffMember.objects.create(
            tenant=self.tenant, user=self.user, role=TenantStaffMember.Role.OWNER,
        )
        self.client.force_authenticate(user=self.user)

    def test_create_form_with_fields(self):
        response = self.client.post(
            "/api/salon/forms/",
            {
                "title": "Ficha de Anamnese",
                "fields": [
                    {"label": "Alergias", "field_type": "textarea", "required": True},
                    {"label": "Gravidez", "field_type": "boolean", "required": True},
                    {"label": "Tipo de pele", "field_type": "select", "options": ["Normal", "Seca", "Oleosa"]},
                ],
            },
            format="json",
        )

        assert response.status_code == status.HTTP_201_CREATED
        data = response.data
        assert data["title"] == "Ficha de Anamnese"
        assert len(data["fields"]) == 3
        assert data["fields"][0]["label"] == "Alergias"
        assert data["fields"][0]["required"] is True
        assert data["fields"][2]["options"] == ["Normal", "Seca", "Oleosa"]

    def test_create_form_empty_fields(self):
        response = self.client.post(
            "/api/salon/forms/",
            {"title": "Formulário Vazio"},
            format="json",
        )
        assert response.status_code == status.HTTP_201_CREATED
        assert response.data["fields"] == []

    def test_list_forms(self):
        TenantForm.objects.create(tenant=self.tenant, title="Form A")
        TenantForm.objects.create(tenant=self.tenant, title="Form B")

        response = self.client.get("/api/salon/forms/")
        assert response.status_code == status.HTTP_200_OK
        assert len(response.data) >= 2

    def test_update_form_replace_fields(self):
        form = TenantForm.objects.create(tenant=self.tenant, title="Old Form")
        TenantFormField.objects.create(form=form, label="Old Field", order=0)

        response = self.client.put(
            f"/api/salon/forms/{form.id}/",
            {
                "title": "Updated Form",
                "fields": [
                    {"label": "New Field", "field_type": "text"},
                ],
            },
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK
        assert response.data["title"] == "Updated Form"
        assert len(response.data["fields"]) == 1
        assert response.data["fields"][0]["label"] == "New Field"

    def test_delete_form(self):
        form = TenantForm.objects.create(tenant=self.tenant, title="To Delete")
        response = self.client.delete(f"/api/salon/forms/{form.id}/")
        assert response.status_code == status.HTTP_204_NO_CONTENT
        assert not TenantForm.objects.filter(id=form.id).exists()

    def test_tenant_isolation(self):
        """Outro tenant não vê formulários deste."""
        TenantForm.objects.create(tenant=self.tenant, title="Private Form")

        other_tenant = Tenant.objects.create(name="Other", slug="other")
        other_user = CustomUser.objects.create_user(
            username="other", email="other@test.com", password="test123",
            tenant=other_tenant,
        )
        TenantStaffMember.objects.create(
            tenant=other_tenant, user=other_user, role=TenantStaffMember.Role.OWNER,
        )

        self.client.force_authenticate(user=other_user)
        response = self.client.get("/api/salon/forms/")
        assert response.status_code == status.HTTP_200_OK
        titles = [f["title"] for f in response.data]
        assert "Private Form" not in titles


@pytest.mark.django_db
class TestCustomerFormResponse:

    def setup_method(self):
        self.client = APIClient()
        self.tenant = Tenant.objects.create(name="Clinic", slug="clinic")
        self.user = CustomUser.objects.create_user(
            username="staff", email="staff@clinic.com", password="test123",
            tenant=self.tenant,
        )
        TenantStaffMember.objects.create(
            tenant=self.tenant, user=self.user, role=TenantStaffMember.Role.OWNER,
        )
        self.client.force_authenticate(user=self.user)

        self.customer = SalonCustomer.objects.create(
            tenant=self.tenant, name="Paciente", email="p@test.com",
        )
        self.form = TenantForm.objects.create(tenant=self.tenant, title="Anamnese")
        self.field_allergy = TenantFormField.objects.create(
            form=self.form, label="Alergias", field_type="textarea", required=True, order=0,
        )
        self.field_smoke = TenantFormField.objects.create(
            form=self.form, label="Fumante", field_type="boolean", required=False, order=1,
        )

    def test_create_response(self):
        response = self.client.post(
            "/api/salon/form-responses/",
            {
                "form": self.form.id,
                "customer": self.customer.id,
                "answers": [
                    {"field_id": self.field_allergy.id, "value": "Penicilina"},
                    {"field_id": self.field_smoke.id, "value": "false"},
                ],
            },
            format="json",
        )

        assert response.status_code == status.HTTP_201_CREATED
        assert len(response.data["answers"]) == 2

    def test_create_response_missing_required(self):
        response = self.client.post(
            "/api/salon/form-responses/",
            {
                "form": self.form.id,
                "customer": self.customer.id,
                "answers": [
                    {"field_id": self.field_smoke.id, "value": "true"},
                ],
            },
            format="json",
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_create_response_required_empty(self):
        response = self.client.post(
            "/api/salon/form-responses/",
            {
                "form": self.form.id,
                "customer": self.customer.id,
                "answers": [
                    {"field_id": self.field_allergy.id, "value": ""},
                ],
            },
            format="json",
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_update_response(self):
        resp = CustomerFormResponse.objects.create(
            form=self.form, customer=self.customer,
        )
        resp.answers.create(field=self.field_allergy, value="Nenhuma")

        response = self.client.patch(
            f"/api/salon/form-responses/{resp.id}/",
            {
                "answers": [
                    {"field_id": self.field_allergy.id, "value": "Ibuprofeno"},
                ],
            },
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK
        resp.refresh_from_db()
        assert resp.answers.get(field=self.field_allergy).value == "Ibuprofeno"

    def test_filter_by_customer(self):
        CustomerFormResponse.objects.create(form=self.form, customer=self.customer)

        response = self.client.get(
            f"/api/salon/form-responses/?customer={self.customer.id}"
        )
        assert response.status_code == status.HTTP_200_OK
        assert len(response.data) == 1

    def test_unique_form_customer(self):
        """Não pode ter duas respostas do mesmo cliente para mesmo formulário."""
        CustomerFormResponse.objects.create(form=self.form, customer=self.customer)

        response = self.client.post(
            "/api/salon/form-responses/",
            {
                "form": self.form.id,
                "customer": self.customer.id,
                "answers": [
                    {"field_id": self.field_allergy.id, "value": "Nada"},
                ],
            },
            format="json",
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_cross_tenant_form_rejected(self):
        """Staff não pode criar resposta referenciando form de outro tenant."""
        other_tenant = Tenant.objects.create(name="Other", slug="other-t")
        other_form = TenantForm.objects.create(tenant=other_tenant, title="Alien Form")

        response = self.client.post(
            "/api/salon/form-responses/",
            {
                "form": other_form.id,
                "customer": self.customer.id,
                "answers": [],
            },
            format="json",
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_cross_tenant_customer_rejected(self):
        """Staff não pode criar resposta referenciando customer de outro tenant."""
        other_tenant = Tenant.objects.create(name="Other2", slug="other2-t")
        other_customer = SalonCustomer.objects.create(
            tenant=other_tenant, name="Alien", email="alien@test.com",
        )

        response = self.client.post(
            "/api/salon/form-responses/",
            {
                "form": self.form.id,
                "customer": other_customer.id,
                "answers": [
                    {"field_id": self.field_allergy.id, "value": "None"},
                ],
            },
            format="json",
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_field_must_belong_to_form(self):
        """Campo de outro formulário não pode ser usado."""
        other_form = TenantForm.objects.create(tenant=self.tenant, title="Other")
        other_field = TenantFormField.objects.create(
            form=other_form, label="Intruso", order=0,
        )

        response = self.client.post(
            "/api/salon/form-responses/",
            {
                "form": self.form.id,
                "customer": self.customer.id,
                "answers": [
                    {"field_id": self.field_allergy.id, "value": "Ok"},
                    {"field_id": other_field.id, "value": "Hack"},
                ],
            },
            format="json",
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST

