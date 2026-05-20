import pytest
from django.utils import timezone
from datetime import timedelta
from cms.models import PublicPage
from cms.tasks import publish_scheduled_pages


@pytest.mark.django_db
def test_scheduled_page_is_published_when_due():
    page = PublicPage.objects.create(
        slug="agendada",
        title="Pagina Agendada",
        content="Conteudo.",
        scheduled_publish_at=timezone.now() - timedelta(minutes=1),
    )
    result = publish_scheduled_pages()
    page.refresh_from_db()
    assert page.status == PublicPage.STATUS_PUBLISHED
    assert result["published"] == 1
    assert result["errors"] == 0


@pytest.mark.django_db
def test_future_scheduled_page_is_not_published():
    page = PublicPage.objects.create(
        slug="futura",
        title="Pagina Futura",
        content="Conteudo.",
        scheduled_publish_at=timezone.now() + timedelta(hours=1),
    )
    publish_scheduled_pages()
    page.refresh_from_db()
    assert page.status == PublicPage.STATUS_DRAFT


@pytest.mark.django_db
def test_already_published_page_is_not_affected():
    page = PublicPage.objects.create(
        slug="ja-publicada",
        title="Ja Publicada",
        content="Conteudo.",
        scheduled_publish_at=timezone.now() - timedelta(minutes=5),
    )
    page.publish()
    result = publish_scheduled_pages()
    assert result["published"] == 0
