from django.urls import include, path
from rest_framework.routers import DefaultRouter

from raffles.views import RaffleViewSet

router = DefaultRouter()
router.register("", RaffleViewSet, basename="raffle")

urlpatterns = [
    path("", include(router.urls)),
]
