from django.urls import path

from downloads import views

urlpatterns = [
    path("download/search", views.download_search, name="download_search"),
    path("download/add", views.download_add, name="download_add"),
    path("download/progress", views.download_progress, name="download_progress"),
]
