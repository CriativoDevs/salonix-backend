from django.urls import path, include

from rest_framework.routers import DefaultRouter

from core.views import (
    AppointmentCancelView,
    AppointmentCreateView,
    AppointmentDetailView,
    AppointmentICSDownloadView,
    BulkAppointmentCreateView,
    MyAppointmentsListView,
    ProfessionalViewSet,
    PublicServiceListView,
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
    path("public/services/", PublicServiceListView.as_view()),
    path("public/professionals/", PublicProfessionalListView.as_view()),
    path("public/slots/", PublicSlotListView.as_view()),
    path("appointments/", AppointmentCreateView.as_view(), name="appointment-create"),
    path(
        "appointments/bulk/",
        BulkAppointmentCreateView.as_view(),
        name="appointment-bulk-create",
    ),
    path(
        "appointments/<int:pk>/cancel/",
        AppointmentCancelView.as_view(),
        name="appointment-cancel",
    ),
    # meu histórico como cliente
    path("me/appointments/", MyAppointmentsListView.as_view(), name="my-appointments"),
    path(
        "appointments/<int:pk>/",
        AppointmentDetailView.as_view(),
        name="appointment-detail",
    ),
    # Download .ics calendar file
    path(
        "appointments/<int:pk>/ics/",
        AppointmentICSDownloadView.as_view(),
        name="appointment-ics-download",
    ),
]
