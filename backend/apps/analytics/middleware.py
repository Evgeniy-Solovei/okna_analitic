from django.db import OperationalError, connection
from django.http import HttpResponse


class ShortWebQueryTimeoutMiddleware:
    """Веб-запросы не ждут БД минутами, если фон занял Postgres."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        with connection.cursor() as cursor:
            # Не ждать блокировки и не крутить запрос дольше 5 секунд.
            cursor.execute("SET lock_timeout TO '3000'")
            cursor.execute("SET statement_timeout TO '5000'")
        try:
            return self.get_response(request)
        except OperationalError as exc:
            message = str(exc).lower()
            if (
                "statement timeout" in message
                or "canceling statement" in message
                or "lock timeout" in message
            ):
                return HttpResponse(
                    "<!doctype html><html lang='ru'><head><meta charset='utf-8'>"
                    "<meta http-equiv='refresh' content='2'>"
                    "<title>Сервер занят</title></head><body style='font-family:sans-serif;padding:40px'>"
                    "<h1>База сейчас занята фоновым обновлением</h1>"
                    "<p>Повтор через 2 секунды. Фильтры Bitrix не запускают — это ожидание БД.</p>"
                    "</body></html>",
                    status=503,
                    content_type="text/html; charset=utf-8",
                )
            raise
        finally:
            try:
                with connection.cursor() as cursor:
                    cursor.execute("SET lock_timeout TO DEFAULT")
                    cursor.execute("SET statement_timeout TO DEFAULT")
            except Exception:
                pass
