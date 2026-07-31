from django.urls import include, path
from rest_framework.routers import DefaultRouter

from inventory.views import (
    InventoryAlertListView,
    InventoryItemViewSet,
    StockMovementViewSet,
)

router = DefaultRouter()
router.register("items", InventoryItemViewSet, basename="inventory-item")
router.register("movements", StockMovementViewSet, basename="stock-movement")

urlpatterns = [
    path("alerts/", InventoryAlertListView.as_view(), name="inventory-alerts"),
    path("", include(router.urls)),
]
