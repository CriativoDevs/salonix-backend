from django.urls import path

from ops.views import OpsAuthLoginView, OpsAuthRefreshView

urlpatterns = [
    path("auth/login/", OpsAuthLoginView.as_view(), name="ops_auth_login"),
    path("auth/refresh/", OpsAuthRefreshView.as_view(), name="ops_auth_refresh"),
]
