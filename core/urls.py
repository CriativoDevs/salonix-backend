from django.urls import path, include

from rest_framework.routers import DefaultRouter

from core.views import (
    AppointmentCancelView,
    AppointmentCreateView,
    AppointmentDetailView,
    AppointmentICSDownloadView,
    AppointmentICSDownloadPublicView,
    AppointmentSeriesOccurrenceCancelView,
    BulkAppointmentCreateView,
    MixedBulkAppointmentCreateView,
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
    ClientAccessLinkView,
    ClientAccessAcceptView,
    ClientSessionRefreshView,
    PublicClientAccessLinkView,
    ClientsMeAppointmentsUpcomingView,
    ClientsMeAppointmentsHistoryView,
    ClientsMeProfileView,
    ClientAppointmentCancelView,
)

router = DefaultRouter()
router.register("services", ServiceViewSet, basename="service")
router.register("professionals", ProfessionalViewSet, basename="professional")
router.register("slots", ScheduleSlotViewSet, basename="slot")
router.register(
    "salon/appointments", SalonAppointmentViewSet, basename="salon-appointments"
)
router.register("salon/customers", SalonCustomerViewSet, basename="salon-customers")

urlpatterns = [
    path("", include(router.urls)),
    path("auth/", include("users.urls")),
    path(
        "clients/access-link/",
        ClientAccessLinkView.as_view(),
        name="clients_access_link",
    ),
    path(
        "clients/access-accept/",
        ClientAccessAcceptView.as_view(),
        name="clients_access_accept",
    ),
    path(
        "clients/session/refresh/",
        ClientSessionRefreshView.as_view(),
        name="clients_session_refresh",
    ),
    # Cliente autenticado via cookie de sessão
    path(
        "clients/me/appointments/upcoming/",
        ClientsMeAppointmentsUpcomingView.as_view(),
        name="clients_me_appointments_upcoming",
    ),
    path(
        "clients/me/appointments/history/",
        ClientsMeAppointmentsHistoryView.as_view(),
        name="clients_me_appointments_history",
    ),
    path(
        "clients/me/profile/",
        ClientsMeProfileView.as_view(),
        name="clients_me_profile",
    ),
    path(
        "clients/me/appointments/<int:pk>/cancel/",
        ClientAppointmentCancelView.as_view(),
        name="clients_me_appointment_cancel",
    ),
    # Public routes
    path(
        "public/clients/access-link/",
        PublicClientAccessLinkView.as_view(),
        name="public_clients_access_link",
    ),
    path("public/services/", PublicServiceListView.as_view()),
    path("public/professionals/", PublicProfessionalListView.as_view()),
    path("public/slots/", PublicSlotListView.as_view()),
    path(
        "public/appointments/<int:pk>/ics/",
        AppointmentICSDownloadPublicView.as_view(),
        name="appointment-ics-download-public",
    ),
    path("appointments/", AppointmentCreateView.as_view(), name="appointment-create"),
    path(
        "appointments/bulk/",
        BulkAppointmentCreateView.as_view(),
        name="appointment-bulk-create",
    ),
    path(
        "appointments/bulk/mixed/",
        MixedBulkAppointmentCreateView.as_view(),
        name="appointment-mixed-bulk-create",
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
