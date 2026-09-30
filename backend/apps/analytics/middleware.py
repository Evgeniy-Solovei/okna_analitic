"""Диагностика БД. Без request middleware — не вмешиваемся в загрузку страниц."""

from django.db import connection
from django.http import JsonResponse


def db_health(_request):
    payload = {"ok": True}
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT pid, state, wait_event_type, wait_event,
                       now() - query_start AS duration,
                       left(query, 180) AS query
                FROM pg_stat_activity
                WHERE datname = current_database()
                  AND pid <> pg_backend_pid()
                ORDER BY query_start NULLS LAST
                """
            )
            cols = [c[0] for c in cursor.description]
            rows = [dict(zip(cols, row)) for row in cursor.fetchall()]
            for row in rows:
                if row.get("duration") is not None:
                    row["duration"] = str(row["duration"])
            payload["activity"] = rows
    except Exception as exc:
        payload["ok"] = False
        payload["error"] = str(exc)
        return JsonResponse(payload, status=503)
    return JsonResponse(payload, json_dumps_params={"ensure_ascii": False, "indent": 2})
