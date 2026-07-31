from django.urls import include, path
from rest_framework.routers import DefaultRouter

from inventory.views import InventoryItemViewSet, StockMovementViewSet

router = DefaultRouter()
router.register("items", InventoryItemViewSet, basename="inventory-item")
router.register("movements", StockMovementViewSet, basename="stock-movement")

urlpatterns = [
    path("", include(router.urls)),
]
