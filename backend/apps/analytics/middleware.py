from django.db import OperationalError, connection
from django.http import HttpResponse


class ShortWebQueryTimeoutMiddleware:
    """Веб-запросы не ждут БД минутами, если фон занял Postgres."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        with connection.cursor() as cursor:
            # 8 секунд: либо страница открылась, либо быстрая ошибка — без «вечного» лоадера.
            cursor.execute("SET statement_timeout TO '8000'")
        try:
            return self.get_response(request)
        except OperationalError as exc:
            message = str(exc).lower()
            if "statement timeout" in message or "canceling statement" in message:
                return HttpResponse(
                    "<!doctype html><html lang='ru'><head><meta charset='utf-8'>"
                    "<meta http-equiv='refresh' content='3'>"
                    "<title>Сервер занят</title></head><body style='font-family:sans-serif;padding:40px'>"
                    "<h1>Сервер сейчас обновляет данные</h1>"
                    "<p>Страница откроется автоматически через пару секунд. "
                    "Это не зависание фильтра — идёт фоновый sync.</p>"
                    "</body></html>",
                    status=503,
                    content_type="text/html; charset=utf-8",
                )
            raise
        finally:
            try:
                with connection.cursor() as cursor:
                    cursor.execute("SET statement_timeout TO DEFAULT")
            except Exception:
                pass
