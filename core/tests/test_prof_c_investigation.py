import pytest
from rest_framework.test import APIClient
from core.models import Professional


@pytest.mark.django_db
def test_professionals_list_identical_web_vs_mobile(user_fixture):
    """
    Investigação BE-PROF-01 item C: confirma que GET /api/professionals/
    retorna o mesmo resultado independentemente de headers extras que o
    webapp poderia enviar (ex.: X-Tenant-Slug), já que ProfessionalViewSet
    (via TenantIsolatedMixin) resolve o tenant exclusivamente a partir de
    request.user.tenant (setado pelo TenantMiddleware), nunca de headers.
    """
    owner_staff = user_fixture.staff_member
    Professional.objects.create(
        tenant=user_fixture.tenant,
        user=user_fixture,
        staff_member=owner_staff,
        name="Owner Prof",
    )

    # Simula client "mobile": só Authorization (JWT), sem headers extras.
    mobile_client = APIClient()
    mobile_client.force_authenticate(user=user_fixture)
    mobile_resp = mobile_client.get("/api/professionals/")

    # Simula client "web": mesmo usuário, mas com header X-Tenant-Slug
    # (o que o ExportCSVBaseView suporta em outros endpoints) e um
    # X-Tenant-Slug incorreto de propósito, para provar que o endpoint
    # de Professional o ignora completamente.
    web_client = APIClient()
    web_client.force_authenticate(user=user_fixture)
    web_resp = web_client.get(
        "/api/professionals/", HTTP_X_TENANT_SLUG="algum-outro-slug-invalido"
    )

    assert mobile_resp.status_code == 200
    assert web_resp.status_code == 200
    mobile_ids = {p["id"] for p in mobile_resp.data}
    web_ids = {p["id"] for p in web_resp.data}
    assert mobile_ids == web_ids
    assert len(mobile_ids) == 1
