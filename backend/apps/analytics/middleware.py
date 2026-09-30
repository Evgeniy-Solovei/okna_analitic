import logging
import time
from threading import local

from django.db import OperationalError, connection
from django.http import HttpResponse, JsonResponse


logger = logging.getLogger("apps.analytics.timing")

_local = local()


class ShortWebQueryTimeoutMiddleware:
    """Лимиты БД + тайминги: видно, дошёл ли запрос до Django и где завис."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request_id = f"{time.time_ns() % 10_000_000:07d}"
        request.analytics_request_id = request_id
        path = request.get_full_path()
        started = time.monotonic()
        _local.request_id = request_id
        _local.slow_sql = []
        _local.sql_count = 0
        _local.sql_total_ms = 0.0

        logger.info("REQ START id=%s %s %s", request_id, request.method, path)

        db_setup_ms = self._apply_timeouts()
        logger.info("REQ DBREADY id=%s setup_ms=%.0f", request_id, db_setup_ms)

        self._install_sql_timer()
        status = 500
        try:
            response = self.get_response(request)
            status = getattr(response, "status_code", 0)
            return response
        except OperationalError as exc:
            message = str(exc).lower()
            elapsed_ms = (time.monotonic() - started) * 1000
            logger.error(
                "REQ DBTIMEOUT id=%s ms=%.0f sql=%s sql_ms=%.0f err=%s path=%s",
                request_id,
                elapsed_ms,
                getattr(_local, "sql_count", 0),
                getattr(_local, "sql_total_ms", 0.0),
                exc,
                path,
            )
            if (
                "statement timeout" in message
                or "canceling statement" in message
                or "lock timeout" in message
            ):
                status = 503
                return HttpResponse(
                    "<!doctype html><html lang='ru'><head><meta charset='utf-8'>"
                    "<meta http-equiv='refresh' content='3'>"
                    "<title>Сервер занят</title></head><body style='font-family:sans-serif;padding:40px'>"
                    "<h1>База сейчас занята</h1>"
                    f"<p>Запрос оборван по timeout за {elapsed_ms:.0f} мс. "
                    "Откройте /health/db/ в другой вкладке — там текущие SQL.</p>"
                    "</body></html>",
                    status=503,
                    content_type="text/html; charset=utf-8",
                )
            raise
        finally:
            elapsed_ms = (time.monotonic() - started) * 1000
            slow = getattr(_local, "slow_sql", []) or []
            logger.info(
                "REQ END id=%s status=%s ms=%.0f sql=%s sql_ms=%.0f slow=%s path=%s",
                request_id,
                status,
                elapsed_ms,
                getattr(_local, "sql_count", 0),
                getattr(_local, "sql_total_ms", 0.0),
                len(slow),
                path,
            )
            for item in slow[:8]:
                logger.warning(
                    "SLOW SQL id=%s ms=%.0f sql=%s",
                    request_id,
                    item["ms"],
                    item["sql"],
                )
            self._remove_sql_timer()
            _local.request_id = None

    @staticmethod
    def _apply_timeouts() -> float:
        t0 = time.monotonic()
        try:
            with connection.cursor() as cursor:
                cursor.execute("SET lock_timeout TO '3000'")
                cursor.execute("SET statement_timeout TO '15000'")
        except Exception:
            logger.exception("REQ DBSETUP failed")
        return (time.monotonic() - t0) * 1000

    def _install_sql_timer(self):
        from django.db.backends.utils import CursorWrapper

        if getattr(CursorWrapper, "_analytics_timing_patched", False):
            return

        original_execute = CursorWrapper.execute
        original_executemany = CursorWrapper.executemany

        def timed_execute(self, sql, params=None):
            return _timed_sql(original_execute, self, sql, params)

        def timed_executemany(self, sql, param_list):
            return _timed_sql(original_executemany, self, sql, param_list)

        CursorWrapper.execute = timed_execute
        CursorWrapper.executemany = timed_executemany
        CursorWrapper._analytics_timing_patched = True
        CursorWrapper._analytics_original_execute = original_execute
        CursorWrapper._analytics_original_executemany = original_executemany

    @staticmethod
    def _remove_sql_timer():
        # патч глобальный на процесс — оставляем
        pass


def _timed_sql(original, cursor, sql, params):
    t0 = time.monotonic()
    try:
        return original(cursor, sql, params)
    finally:
        ms = (time.monotonic() - t0) * 1000
        if hasattr(_local, "sql_count"):
            _local.sql_count = getattr(_local, "sql_count", 0) + 1
            _local.sql_total_ms = getattr(_local, "sql_total_ms", 0.0) + ms
            if ms >= 200:
                slow = getattr(_local, "slow_sql", None)
                if slow is not None:
                    sql_text = " ".join(str(sql).split())
                    slow.append({"ms": ms, "sql": sql_text[:300]})


def db_health(_request):
    """Диагностика зависаний: что сейчас делает Postgres."""
    payload = {
        "ok": True,
        "server_time": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
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

            cursor.execute(
                """
                SELECT locktype, mode, granted, relation::regclass::text AS relation
                FROM pg_locks
                WHERE database = (SELECT oid FROM pg_database WHERE datname = current_database())
                ORDER BY granted, relation
                LIMIT 50
                """
            )
            cols = [c[0] for c in cursor.description]
            payload["locks"] = [dict(zip(cols, row)) for row in cursor.fetchall()]

            cursor.execute("SELECT count(*) FROM manager_daily_metrics")
            payload["manager_daily_metrics"] = cursor.fetchone()[0]
            cursor.execute("SELECT count(*) FROM measurer_daily_metrics")
            payload["measurer_daily_metrics"] = cursor.fetchone()[0]
    except Exception as exc:
        payload["ok"] = False
        payload["error"] = str(exc)
        return JsonResponse(payload, status=503)
    return JsonResponse(payload, json_dumps_params={"ensure_ascii": False, "indent": 2})
