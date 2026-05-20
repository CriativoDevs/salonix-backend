import pytest
from django.utils import timezone
from datetime import timedelta
from cms.models import PublicPage, PageSEO


@pytest.mark.django_db
def test_create_page_defaults_to_draft():
    page = PublicPage.objects.create(
        slug="tutorial-basico",
        title="Tutorial Basico",
        content="Conteudo do tutorial.",
    )
    assert page.status == PublicPage.STATUS_DRAFT
    assert page.published_at is None


@pytest.mark.django_db
def test_publish_sets_status_and_published_at():
    page = PublicPage.objects.create(
        slug="tutorial-pub",
        title="Tutorial",
        content="Conteudo.",
    )
    page.publish()
    assert page.status == PublicPage.STATUS_PUBLISHED
    assert page.published_at is not None


@pytest.mark.django_db
def test_unpublish_reverts_to_draft():
    page = PublicPage.objects.create(
        slug="tutorial-unpub",
        title="Tutorial",
        content="Conteudo.",
    )
    page.publish()
    page.unpublish()
    assert page.status == PublicPage.STATUS_DRAFT


@pytest.mark.django_db
def test_slug_unique():
    PublicPage.objects.create(slug="slug-unico", title="A", content="x")
    with pytest.raises(Exception):
        PublicPage.objects.create(slug="slug-unico", title="B", content="y")


@pytest.mark.django_db
def test_pageseo_linked_to_page():
    page = PublicPage.objects.create(slug="seo-page", title="SEO", content="x")
    seo = PageSEO.objects.create(
        page=page,
        meta_title="Meta Title",
        meta_description="Meta Description",
    )
    assert seo.page == page
    assert str(seo) == f"SEO: {page.title}"
