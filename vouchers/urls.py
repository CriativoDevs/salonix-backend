from django.urls import include, path
from rest_framework.routers import DefaultRouter

from vouchers.views import VoucherViewSet

router = DefaultRouter()
router.register("", VoucherViewSet, basename="voucher")

urlpatterns = [
    path("", include(router.urls)),
]
