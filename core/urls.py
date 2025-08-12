from django.urls import path, include

from rest_framework.routers import DefaultRouter

from core.views import (
    AppointmentCancelView,
    AppointmentCreateView,
    ProfessionalViewSet,
    PublicProfessionalListView,
    PublicSlotListView,
    SalonAppointmentViewSet,
    ServiceViewSet,
    ScheduleSlotViewSet,
)

router = DefaultRouter()
router.register("services", ServiceViewSet, basename="service")
router.register("professionals", ProfessionalViewSet, basename="professional")
router.register("slots", ScheduleSlotViewSet, basename="slot")
router.register(
    "salon/appointments", SalonAppointmentViewSet, basename="salon-appointments"
)

urlpatterns = [
    path("", include(router.urls)),
    path("auth/", include("users.urls")),
    # Public routes
    path(
        "professionals/",
        PublicProfessionalListView.as_view(),
        name="public-professional-list",
    ),
    path("slots/", PublicSlotListView.as_view(), name="public-slot-list"),
    path("appointments/", AppointmentCreateView.as_view(), name="appointment-create"),
    path(
        "appointments/<int:pk>/cancel/",
        AppointmentCancelView.as_view(),
        name="appointment-cancel",
    ),
]
