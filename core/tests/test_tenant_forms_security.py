"""
BE-ANAMNESE-01: testes de autorizacao dos endpoints de formularios.

Usam tokens JWT reais (staff e cliente), sem mock de autenticacao.
"""

import pytest
from rest_framework import status
from rest_framework.test import APIClient

from core.models import (
    CustomerFormResponse,
    SalonCustomer,
    TenantForm,
    TenantFormField,
)
from core.views import _create_client_jwt_tokens
from users.models import CustomUser, Tenant, TenantStaffMember


def _make_tenant(slug):
    return Tenant.objects.create(
        name=slug, slug=slug, plan_tier=Tenant.PLAN_BASIC, pwa_client_enabled=True
    )


def _make_staff(tenant, username, role):
    user = CustomUser.objects.create_user(
        username=username,
        email=f"{username}@test.com",
        password="pass12345",
        tenant=tenant,
    )
    TenantStaffMember.objects.create(tenant=tenant, user=user, role=role)
    return user


def _client_api(tenant, customer):
    api = APIClient()
    tokens = _create_client_jwt_tokens(tenant, customer)
    api.credentials(HTTP_AUTHORIZATION=f"Bearer {tokens['access']}")
    return api


@pytest.mark.django_db
class TestStaffEndpointsRejectClientTokens:
    """Token scope=client leva user_id == customer.id; nao pode valer como staff."""

    def test_client_token_aliasing_staff_user_is_rejected(self):
        tenant_a = _make_tenant("tenant-a")
        staff = _make_staff(tenant_a, "staff-a", TenantStaffMember.Role.OWNER)
        TenantForm.objects.create(tenant=tenant_a, title="Ficha A")

        tenant_b = _make_tenant("tenant-b")
        customer = SalonCustomer.objects.create(
            id=staff.id, tenant=tenant_b, name="Cliente B", email="b@test.com"
        )
        assert customer.id == staff.id

        api = _client_api(tenant_b, customer)
        # BE-SEC-01: recusado na autenticacao global (401), antes da permissao.

        assert api.get("/api/salon/forms/").status_code == status.HTTP_401_UNAUTHORIZED
        assert (
            api.get("/api/salon/form-responses/").status_code
            == status.HTTP_401_UNAUTHORIZED
        )
        assert (
            api.post(
                "/api/salon/forms/", {"title": "Hack"}, format="json"
            ).status_code
            == status.HTTP_401_UNAUTHORIZED
        )

    def test_user_without_staff_record_is_rejected(self):
        tenant = _make_tenant("no-staff")
        user = CustomUser.objects.create_user(
            username="nostaff",
            email="nostaff@test.com",
            password="pass12345",
            tenant=tenant,
        )
        api = APIClient()
        api.force_authenticate(user=user)

        assert api.get("/api/salon/forms/").status_code == status.HTTP_403_FORBIDDEN
        assert (
            api.get("/api/salon/form-responses/").status_code
            == status.HTTP_403_FORBIDDEN
        )


@pytest.mark.django_db
class TestFormDefinitionRoles:
    def setup_method(self):
        self.tenant = _make_tenant("roles")
        self.collab = _make_staff(
            self.tenant, "collab", TenantStaffMember.Role.COLLABORATOR
        )
        self.manager = _make_staff(
            self.tenant, "manager", TenantStaffMember.Role.MANAGER
        )
        self.form = TenantForm.objects.create(tenant=self.tenant, title="Anamnese")

    def _api(self, user):
        api = APIClient()
        api.force_authenticate(user=user)
        return api

    def test_collaborator_can_read_forms(self):
        response = self._api(self.collab).get("/api/salon/forms/")
        assert response.status_code == status.HTTP_200_OK

    def test_collaborator_cannot_write_or_delete_forms(self):
        api = self._api(self.collab)
        create = api.post("/api/salon/forms/", {"title": "X"}, format="json")
        update = api.put(
            f"/api/salon/forms/{self.form.id}/", {"title": "Y"}, format="json"
        )
        delete = api.delete(f"/api/salon/forms/{self.form.id}/")

        assert create.status_code == status.HTTP_403_FORBIDDEN
        assert update.status_code == status.HTTP_403_FORBIDDEN
        assert delete.status_code == status.HTTP_403_FORBIDDEN
        assert TenantForm.objects.filter(id=self.form.id).exists()

    def test_manager_can_write_forms(self):
        response = self._api(self.manager).post(
            "/api/salon/forms/", {"title": "Nova"}, format="json"
        )
        assert response.status_code == status.HTTP_201_CREATED


@pytest.mark.django_db
class TestClientFormResponseEndpoint:
    def setup_method(self):
        self.tenant = _make_tenant("spa")
        self.customer = SalonCustomer.objects.create(
            tenant=self.tenant, name="Cliente", email="c@spa.com"
        )
        self.form = TenantForm.objects.create(
            tenant=self.tenant, title="Intake", client_editable=False
        )
        self.field = TenantFormField.objects.create(
            form=self.form, label="Notas", field_type="text", order=0
        )
        self.resp = CustomerFormResponse.objects.create(
            form=self.form, customer=self.customer
        )
        self.resp.answers.create(field=self.field, value="Inicial")
        self.api = _client_api(self.tenant, self.customer)

    def test_client_reads_own_responses(self):
        response = self.api.get("/api/clients/me/form-responses/")

        assert response.status_code == status.HTTP_200_OK
        assert [r["id"] for r in response.data] == [self.resp.id]

    def test_client_reads_single_own_response(self):
        response = self.api.get(f"/api/clients/me/form-responses/{self.resp.id}/")

        assert response.status_code == status.HTTP_200_OK
        assert response.data["id"] == self.resp.id

    def test_client_does_not_see_other_customers_responses(self):
        other = SalonCustomer.objects.create(
            tenant=self.tenant, name="Outro", email="o@spa.com"
        )
        other_resp = CustomerFormResponse.objects.create(
            form=self.form, customer=other
        )

        listing = self.api.get("/api/clients/me/form-responses/")
        detail = self.api.get(f"/api/clients/me/form-responses/{other_resp.id}/")

        assert other_resp.id not in [r["id"] for r in listing.data]
        assert detail.status_code == status.HTTP_404_NOT_FOUND

    def test_client_cannot_edit_other_customers_response(self):
        self.form.client_editable = True
        self.form.save()
        other = SalonCustomer.objects.create(
            tenant=self.tenant, name="Outro", email="o@spa.com"
        )
        other_resp = CustomerFormResponse.objects.create(
            form=self.form, customer=other
        )

        response = self.api.put(
            f"/api/clients/me/form-responses/{other_resp.id}/",
            {"answers": [{"field_id": self.field.id, "value": "Hack"}]},
            format="json",
        )

        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_client_cannot_edit_when_form_not_editable(self):
        response = self.api.put(
            f"/api/clients/me/form-responses/{self.resp.id}/",
            {"answers": [{"field_id": self.field.id, "value": "Mudou"}]},
            format="json",
        )

        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert self.resp.answers.get(field=self.field).value == "Inicial"

    def test_client_can_edit_when_form_editable(self):
        self.form.client_editable = True
        self.form.save()

        response = self.api.put(
            f"/api/clients/me/form-responses/{self.resp.id}/",
            {"answers": [{"field_id": self.field.id, "value": "Atualizado"}]},
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK
        assert self.resp.answers.get(field=self.field).value == "Atualizado"

    def test_client_cannot_switch_form_or_customer_on_edit(self):
        self.form.client_editable = True
        self.form.save()
        other_form = TenantForm.objects.create(
            tenant=self.tenant, title="Outro", client_editable=True
        )
        other = SalonCustomer.objects.create(
            tenant=self.tenant, name="Outro", email="o@spa.com"
        )

        self.api.put(
            f"/api/clients/me/form-responses/{self.resp.id}/",
            {
                "form": other_form.id,
                "customer": other.id,
                "answers": [{"field_id": self.field.id, "value": "X"}],
            },
            format="json",
        )

        self.resp.refresh_from_db()
        assert self.resp.form_id == self.form.id
        assert self.resp.customer_id == self.customer.id

    def test_client_cannot_answer_field_of_another_form(self):
        self.form.client_editable = True
        self.form.save()
        other_form = TenantForm.objects.create(tenant=self.tenant, title="Outro")
        foreign_field = TenantFormField.objects.create(
            form=other_form, label="Intruso", order=0
        )

        response = self.api.put(
            f"/api/clients/me/form-responses/{self.resp.id}/",
            {"answers": [{"field_id": foreign_field.id, "value": "Hack"}]},
            format="json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_staff_token_is_rejected_on_client_endpoint(self):
        staff = _make_staff(self.tenant, "staff-spa", TenantStaffMember.Role.OWNER)
        api = APIClient()
        api.force_authenticate(user=staff)

        response = api.get("/api/clients/me/form-responses/")

        assert response.status_code in (
            status.HTTP_400_BAD_REQUEST,
            status.HTTP_401_UNAUTHORIZED,
            status.HTTP_403_FORBIDDEN,
        )

    def test_missing_token_is_rejected(self):
        response = APIClient().get("/api/clients/me/form-responses/")

        assert response.status_code in (
            status.HTTP_400_BAD_REQUEST,
            status.HTTP_401_UNAUTHORIZED,
            status.HTTP_403_FORBIDDEN,
        )


@pytest.mark.django_db
class TestFormEditPreservesAnswers:
    def test_editing_form_keeps_field_ids_and_customer_answers(self):
        tenant = _make_tenant("edit-form")
        owner = _make_staff(tenant, "owner-edit", TenantStaffMember.Role.OWNER)
        customer = SalonCustomer.objects.create(
            tenant=tenant, name="C", email="c@test.com"
        )
        form = TenantForm.objects.create(tenant=tenant, title="Antes")
        field = TenantFormField.objects.create(form=form, label="Alergias", order=0)
        resp = CustomerFormResponse.objects.create(form=form, customer=customer)
        resp.answers.create(field=field, value="Penicilina")
        api = APIClient()
        api.force_authenticate(user=owner)

        response = api.put(
            f"/api/salon/forms/{form.id}/",
            {
                "title": "Depois",
                "fields": [
                    {"id": field.id, "label": "Alergias (detalhe)", "order": 0},
                    {"label": "Medicação", "order": 1},
                ],
            },
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK
        field.refresh_from_db()
        assert field.label == "Alergias (detalhe)"
        assert resp.answers.get(field=field).value == "Penicilina"
        assert form.fields.count() == 2


@pytest.mark.django_db
class TestPartialUpdateKeepsExistingAnswers:
    def test_patch_one_answer_does_not_require_resending_all_required(self):
        tenant = _make_tenant("partial")
        staff = _make_staff(tenant, "staff-partial", TenantStaffMember.Role.OWNER)
        customer = SalonCustomer.objects.create(
            tenant=tenant, name="P", email="p@test.com"
        )
        form = TenantForm.objects.create(tenant=tenant, title="F")
        f1 = TenantFormField.objects.create(
            form=form, label="A", required=True, order=0
        )
        f2 = TenantFormField.objects.create(
            form=form, label="B", required=True, order=1
        )
        resp = CustomerFormResponse.objects.create(form=form, customer=customer)
        resp.answers.create(field=f1, value="a")
        resp.answers.create(field=f2, value="b")
        api = APIClient()
        api.force_authenticate(user=staff)

        ok = api.patch(
            f"/api/salon/form-responses/{resp.id}/",
            {"answers": [{"field_id": f1.id, "value": "novo"}]},
            format="json",
        )
        blank = api.patch(
            f"/api/salon/form-responses/{resp.id}/",
            {"answers": [{"field_id": f2.id, "value": "  "}]},
            format="json",
        )

        assert ok.status_code == status.HTTP_200_OK
        assert resp.answers.get(field=f1).value == "novo"
        assert blank.status_code == status.HTTP_400_BAD_REQUEST
        assert resp.answers.get(field=f2).value == "b"


@pytest.mark.django_db
class TestInactiveOrMismatchedStaffRejected:
    def setup_method(self):
        self.tenant = _make_tenant("status-gate")
        TenantForm.objects.create(tenant=self.tenant, title="Ficha")

    def _api(self, user):
        api = APIClient()
        api.force_authenticate(user=user)
        return api

    @pytest.mark.parametrize(
        "member_status",
        [TenantStaffMember.Status.DISABLED, TenantStaffMember.Status.INVITED],
    )
    def test_non_active_staff_has_no_access(self, member_status):
        user = _make_staff(
            self.tenant, f"inactive-{member_status}", TenantStaffMember.Role.MANAGER
        )
        TenantStaffMember.objects.filter(user=user).update(status=member_status)
        api = self._api(user)

        assert api.get("/api/salon/forms/").status_code == status.HTTP_403_FORBIDDEN
        assert (
            api.get("/api/salon/form-responses/").status_code
            == status.HTTP_403_FORBIDDEN
        )
        assert (
            api.post("/api/salon/forms/", {"title": "X"}, format="json").status_code
            == status.HTTP_403_FORBIDDEN
        )

    def test_staff_record_from_another_tenant_has_no_access(self):
        other = _make_tenant("status-gate-other")
        user = CustomUser.objects.create_user(
            username="mismatch",
            email="mismatch@test.com",
            password="pass12345",
            tenant=self.tenant,
        )
        TenantStaffMember.objects.create(
            tenant=other, user=user, role=TenantStaffMember.Role.OWNER
        )
        api = self._api(user)

        assert api.get("/api/salon/forms/").status_code == status.HTTP_403_FORBIDDEN
        assert (
            api.post("/api/salon/forms/", {"title": "X"}, format="json").status_code
            == status.HTTP_403_FORBIDDEN
        )


@pytest.mark.django_db
class TestFormCreateIgnoresSuppliedFieldIds:
    def test_supplied_field_id_is_ignored_on_create(self):
        tenant = _make_tenant("create-ids")
        owner = _make_staff(tenant, "owner-ids", TenantStaffMember.Role.OWNER)
        other = _make_tenant("create-ids-other")
        foreign_form = TenantForm.objects.create(tenant=other, title="Alheio")
        foreign_field = TenantFormField.objects.create(
            form=foreign_form, label="Original", order=0
        )
        api = APIClient()
        api.force_authenticate(user=owner)

        response = api.post(
            "/api/salon/forms/",
            {
                "title": "Meu",
                "fields": [
                    {"id": foreign_field.id, "label": "Tentativa", "order": 0},
                    {"id": 999999, "label": "Id escolhido", "order": 1},
                ],
            },
            format="json",
        )

        assert response.status_code == status.HTTP_201_CREATED
        created_ids = [f["id"] for f in response.data["fields"]]
        assert foreign_field.id not in created_ids
        assert 999999 not in created_ids
        foreign_field.refresh_from_db()
        assert foreign_field.label == "Original"
        assert foreign_field.form_id == foreign_form.id


@pytest.mark.django_db
class TestNoCrossTenantLabelLeak:
    SECRET = "ROTULO-SECRETO-DO-TENANT-B"

    def setup_method(self):
        self.tenant = _make_tenant("leak-a")
        self.owner = _make_staff(self.tenant, "owner-leak", TenantStaffMember.Role.OWNER)
        self.customer = SalonCustomer.objects.create(
            tenant=self.tenant, name="C", email="c@leak.com"
        )
        self.form = TenantForm.objects.create(
            tenant=self.tenant, title="A", client_editable=True
        )
        self.field = TenantFormField.objects.create(
            form=self.form, label="Propria", order=0
        )
        self.other_tenant = _make_tenant("leak-b")
        self.other_form = TenantForm.objects.create(tenant=self.other_tenant, title="B")
        self.other_field = TenantFormField.objects.create(
            form=self.other_form, label=self.SECRET, required=True, order=0
        )
        self.other_customer = SalonCustomer.objects.create(
            tenant=self.other_tenant, name="Outro", email="o@leak.com"
        )
        self.staff_api = APIClient()
        self.staff_api.force_authenticate(user=self.owner)

    def test_staff_foreign_form_id_is_rejected_without_labels(self):
        response = self.staff_api.post(
            "/api/salon/form-responses/",
            {"form": self.other_form.id, "customer": self.customer.id, "answers": []},
            format="json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert self.SECRET not in response.content.decode()

    def test_staff_foreign_customer_id_is_rejected(self):
        response = self.staff_api.post(
            "/api/salon/form-responses/",
            {"form": self.form.id, "customer": self.other_customer.id, "answers": []},
            format="json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_staff_foreign_field_id_does_not_leak_label(self):
        response = self.staff_api.post(
            "/api/salon/form-responses/",
            {
                "form": self.form.id,
                "customer": self.customer.id,
                "answers": [
                    {"field_id": self.field.id, "value": "ok"},
                    {"field_id": self.other_field.id, "value": "x"},
                ],
            },
            format="json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert self.SECRET not in response.content.decode()

    def test_client_foreign_field_id_does_not_leak_label(self):
        resp = CustomerFormResponse.objects.create(
            form=self.form, customer=self.customer
        )
        api = _client_api(self.tenant, self.customer)

        response = api.put(
            f"/api/clients/me/form-responses/{resp.id}/",
            {"answers": [{"field_id": self.other_field.id, "value": "x"}]},
            format="json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert self.SECRET not in response.content.decode()

    def test_client_field_of_another_form_same_tenant_does_not_leak_label(self):
        sibling_form = TenantForm.objects.create(tenant=self.tenant, title="Irmao")
        sibling_field = TenantFormField.objects.create(
            form=sibling_form, label=self.SECRET, order=0
        )
        resp = CustomerFormResponse.objects.create(
            form=self.form, customer=self.customer
        )
        api = _client_api(self.tenant, self.customer)

        response = api.put(
            f"/api/clients/me/form-responses/{resp.id}/",
            {"answers": [{"field_id": sibling_field.id, "value": "x"}]},
            format="json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert self.SECRET not in response.content.decode()
