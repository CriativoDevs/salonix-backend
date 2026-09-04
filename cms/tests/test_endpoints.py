import pytest
from django.urls import reverse
from rest_framework.test import APIClient
from cms.models import PublicPage, PageSEO


@pytest.fixture
def client():
    return APIClient()


@pytest.fixture
def published_page():
    page = PublicPage.objects.create(
        slug="tutorial-pub",
        title="Tutorial Publicado",
        summary="Resumo do tutorial.",
        content="Conteudo completo.",
    )
    page.publish()
    PageSEO.objects.create(page=page, meta_title="SEO Title", meta_description="SEO Desc")
    return page


@pytest.fixture
def draft_page():
    return PublicPage.objects.create(
        slug="tutorial-draft",
        title="Tutorial Draft",
        content="Conteudo draft.",
    )


@pytest.mark.django_db
def test_list_returns_only_published(client, published_page, draft_page, user_fixture):
    client.force_authenticate(user_fixture)
    url = reverse("cms-page-list")
    response = client.get(url)
    assert response.status_code == 200
    slugs = [p["slug"] for p in response.data]
    assert "tutorial-pub" in slugs
    assert "tutorial-draft" not in slugs


@pytest.mark.django_db
def test_detail_returns_published_page(client, published_page, user_fixture):
    client.force_authenticate(user_fixture)
    url = reverse("cms-page-detail", kwargs={"slug": "tutorial-pub"})
    response = client.get(url)
    assert response.status_code == 200
    assert response.data["title"] == "Tutorial Publicado"
    assert response.data["seo"]["meta_title"] == "SEO Title"


@pytest.mark.django_db
def test_detail_draft_returns_404(client, draft_page, user_fixture):
    client.force_authenticate(user_fixture)
    url = reverse("cms-page-detail", kwargs={"slug": "tutorial-draft"})
    response = client.get(url)
    assert response.status_code == 404


@pytest.mark.django_db
def test_detail_slug_inexistente_returns_404(client, user_fixture):
    client.force_authenticate(user_fixture)
    url = reverse("cms-page-detail", kwargs={"slug": "nao-existe"})
    response = client.get(url)
    assert response.status_code == 404


@pytest.mark.django_db
def test_list_sem_autenticacao_retorna_401(client, published_page):
    url = reverse("cms-page-list")
    response = client.get(url)
    assert response.status_code == 401


@pytest.mark.django_db
def test_detail_sem_autenticacao_retorna_401(client, published_page):
    url = reverse("cms-page-detail", kwargs={"slug": "tutorial-pub"})
    response = client.get(url)
    assert response.status_code == 401


@pytest.mark.django_db
def test_list_autenticado_retorna_200(client, published_page, user_fixture):
    client.force_authenticate(user_fixture)
    url = reverse("cms-page-list")
    response = client.get(url)
    assert response.status_code == 200
    slugs = [p["slug"] for p in response.data]
    assert "tutorial-pub" in slugs


@pytest.mark.django_db
def test_detail_autenticado_retorna_200(client, published_page, user_fixture):
    client.force_authenticate(user_fixture)
    url = reverse("cms-page-detail", kwargs={"slug": "tutorial-pub"})
    response = client.get(url)
    assert response.status_code == 200
    assert response.data["title"] == "Tutorial Publicado"
