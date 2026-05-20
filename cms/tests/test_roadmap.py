import pytest
from django.urls import reverse
from rest_framework.test import APIClient
from cms.models import RoadmapItem


@pytest.fixture
def client():
    return APIClient()


@pytest.fixture
def visible_item():
    return RoadmapItem.objects.create(
        title="Feature A",
        description="Descricao A",
        status=RoadmapItem.STATUS_PLANNED,
        order=1,
        is_visible=True,
    )


@pytest.fixture
def hidden_item():
    return RoadmapItem.objects.create(
        title="Feature Oculta",
        description="Nao deve aparecer",
        status=RoadmapItem.STATUS_IN_PROGRESS,
        order=2,
        is_visible=False,
    )


@pytest.mark.django_db
def test_roadmap_retorna_apenas_visiveis(client, visible_item, hidden_item):
    url = reverse("cms-roadmap-list")
    response = client.get(url)
    assert response.status_code == 200
    titles = [item["title"] for item in response.data]
    assert "Feature A" in titles
    assert "Feature Oculta" not in titles


@pytest.mark.django_db
def test_roadmap_ordenado_por_order(client):
    RoadmapItem.objects.create(title="Terceiro", order=3, is_visible=True)
    RoadmapItem.objects.create(title="Primeiro", order=1, is_visible=True)
    RoadmapItem.objects.create(title="Segundo", order=2, is_visible=True)
    url = reverse("cms-roadmap-list")
    response = client.get(url)
    titles = [item["title"] for item in response.data]
    assert titles == ["Primeiro", "Segundo", "Terceiro"]


@pytest.mark.django_db
def test_roadmap_endpoint_publico_sem_autenticacao(client, visible_item):
    url = reverse("cms-roadmap-list")
    response = client.get(url)
    assert response.status_code == 200


@pytest.mark.django_db
def test_roadmap_retorna_status_display(client, visible_item):
    url = reverse("cms-roadmap-list")
    response = client.get(url)
    assert response.data[0]["status_display"] == "Planejado"


@pytest.mark.django_db
def test_roadmap_vazio_sem_itens_visiveis(client, hidden_item):
    url = reverse("cms-roadmap-list")
    response = client.get(url)
    assert response.status_code == 200
    assert response.data == []
