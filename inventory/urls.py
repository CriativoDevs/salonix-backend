from django.urls import include, path
from rest_framework.routers import DefaultRouter

from inventory.views import InventoryItemViewSet

router = DefaultRouter()
router.register("items", InventoryItemViewSet, basename="inventory-item")

urlpatterns = [
    path("", include(router.urls)),
]
