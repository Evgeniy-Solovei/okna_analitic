from datetime import timedelta

from django.conf import settings
from django.db import connection
from django.http import JsonResponse
from django.shortcuts import redirect
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


def dashboard_entry(request):
    _on_demand_sync_if_needed(force=request.GET.get("force") == "1")
    return redirect(settings.METABASE_DASHBOARD_PATH)


def refresh_status(request):
    result = _on_demand_sync_if_needed(force=request.GET.get("force") == "1")
    return JsonResponse(result)
