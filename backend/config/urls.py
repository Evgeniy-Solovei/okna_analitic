from django.contrib import admin
from django.http import JsonResponse
from django.urls import include, path

from apps.analytics.middleware import db_health
from apps.analytics.views import dashboard_entry, measurers_dashboard_entry, refresh_status


def health(_request):
    return JsonResponse({"status": "ok"})


urlpatterns = [
    path("", dashboard_entry, name="dashboard"),
    path("measurers/", measurers_dashboard_entry, name="measurers_dashboard"),
    path("accounts/", include("django.contrib.auth.urls")),
    path("refresh/", refresh_status),
    path("admin/", admin.site.urls),
    path("health/", health),
    path("health/db/", db_health),
]
