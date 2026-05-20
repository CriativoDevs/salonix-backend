from django.urls import path
from cms.views import PublicPageListView, PublicPageDetailView

urlpatterns = [
    path("pages/", PublicPageListView.as_view(), name="cms-page-list"),
    path("pages/<slug:slug>/", PublicPageDetailView.as_view(), name="cms-page-detail"),
]
