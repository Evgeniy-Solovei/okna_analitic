from django.contrib import admin
from django.http import JsonResponse
from django.urls import include, path

from apps.analytics.views import dashboard_entry, refresh_status


def health(_request):
    return JsonResponse({"status": "ok"})


urlpatterns = [
    path("", dashboard_entry),
    path("accounts/", include("django.contrib.auth.urls")),
    path("refresh/", refresh_status),
    path("admin/", admin.site.urls),
    path("health/", health),
]
