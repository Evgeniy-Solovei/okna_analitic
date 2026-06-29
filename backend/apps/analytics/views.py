import time
from datetime import timedelta

import jwt
from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.db import connection
from django.http import JsonResponse
from django.shortcuts import render
from django.utils import timezone

from .services import bitrix_datetime, get_sync_cursor, parse_bitrix_datetime, run_bitrix24_sync, set_sync_cursor


SYNC_LOCK_ID = 24062026


def _try_advisory_lock() -> bool:
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_try_advisory_lock(%s)", [SYNC_LOCK_ID])
        return bool(cursor.fetchone()[0])


def _release_advisory_lock():
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_advisory_unlock(%s)", [SYNC_LOCK_ID])


def _on_demand_sync_if_needed(force: bool = False) -> dict:
    if not settings.ON_DEMAND_SYNC_ENABLED:
        return {"skipped": True, "reason": "disabled"}

    now = timezone.now()
    if not get_sync_cursor("bitrix24.modified_at"):
        return {"skipped": True, "reason": "initial_sync_required"}

    last_value = get_sync_cursor("bitrix24.on_demand_last_at")
    last_at = parse_bitrix_datetime(last_value) if last_value else None
    min_interval = timedelta(seconds=settings.ON_DEMAND_SYNC_MIN_INTERVAL_SECONDS)

    if not force and last_at and now - last_at < min_interval:
        return {"skipped": True, "reason": "recent", "last_at": last_value}

    if not _try_advisory_lock():
        return {"skipped": True, "reason": "locked"}

    try:
        stats = run_bitrix24_sync(mode="incremental", source="bitrix24_on_demand")
        set_sync_cursor("bitrix24.on_demand_last_at", bitrix_datetime(now), {"stats": stats})
        return {"skipped": False, "stats": stats}
    finally:
        _release_advisory_lock()


def _metabase_dashboard_id() -> int:
    if settings.METABASE_EMBEDDING_DASHBOARD_ID:
        return int(settings.METABASE_EMBEDDING_DASHBOARD_ID)
    return int(settings.METABASE_DASHBOARD_PATH.rstrip("/").split("/")[-1])


def _metabase_embed_url() -> str:
    payload = {
        "resource": {"dashboard": _metabase_dashboard_id()},
        "params": {},
        "exp": round(time.time()) + 12 * 60 * 60,
    }
    token = jwt.encode(payload, settings.METABASE_EMBEDDING_SECRET_KEY, algorithm="HS256")
    return f"/embed/dashboard/{token}#bordered=false&titled=false"


@login_required
def dashboard_entry(request):
    _on_demand_sync_if_needed(force=request.GET.get("force") == "1")
    if not settings.METABASE_EMBEDDING_SECRET_KEY:
        return render(
            request,
            "analytics/dashboard_not_configured.html",
            {"message": "Не задан METABASE_EMBEDDING_SECRET_KEY."},
            status=503,
        )
    return render(
        request,
        "analytics/dashboard.html",
        {"dashboard_url": _metabase_embed_url()},
    )


@login_required
def refresh_status(request):
    result = _on_demand_sync_if_needed(force=request.GET.get("force") == "1")
    return JsonResponse(result)
