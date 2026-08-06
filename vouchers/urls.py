from django.urls import include, path
from rest_framework.routers import DefaultRouter

from vouchers.views import BirthdayVoucherConfigViewSet, VoucherViewSet

router = DefaultRouter()
router.register(
    "birthday-configs", BirthdayVoucherConfigViewSet, basename="birthday-voucher-config"
)
router.register("", VoucherViewSet, basename="voucher")

urlpatterns = [
    path("", include(router.urls)),
]
