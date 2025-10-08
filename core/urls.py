from django.urls import path, include

from rest_framework.routers import DefaultRouter

from core.views import (
    AppointmentCancelView,
    AppointmentCreateView,
    AppointmentDetailView,
    AppointmentICSDownloadView,
    AppointmentSeriesOccurrenceCancelView,
    BulkAppointmentCreateView,
    MyAppointmentsListView,
    AppointmentSeriesCreateView,
    AppointmentSeriesDetailView,
    ProfessionalViewSet,
    PublicServiceListView,
    PublicProfessionalListView,
    PublicSlotListView,
    SalonAppointmentViewSet,
    SalonCustomerViewSet,
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
router.register(
    "salon/customers", SalonCustomerViewSet, basename="salon-customers"
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
        "appointments/series/",
        AppointmentSeriesCreateView.as_view(),
        name="appointment-series-create",
    ),
    path(
        "appointments/series/<int:pk>/",
        AppointmentSeriesDetailView.as_view(),
        name="appointment-series-detail",
    ),
    path(
        "appointments/series/<int:series_id>/occurrence/<int:occurrence_id>/cancel/",
        AppointmentSeriesOccurrenceCancelView.as_view(),
        name="appointment-series-occurrence-cancel",
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
