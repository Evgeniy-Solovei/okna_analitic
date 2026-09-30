from django.db import OperationalError, connection
from django.http import HttpResponse


class ShortWebQueryTimeoutMiddleware:
    """Ставит лимиты БД ДО session/auth/view — иначе запрос может висеть минутами."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        self._apply_timeouts()
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
                    "<h1>База сейчас занята</h1>"
                    "<p>Повтор через 2 секунды. Фильтр Bitrix не вызывает — это ожидание БД.</p>"
                    "</body></html>",
                    status=503,
                    content_type="text/html; charset=utf-8",
                )
            raise

    @staticmethod
    def _apply_timeouts():
        try:
            with connection.cursor() as cursor:
                cursor.execute("SET lock_timeout TO '2000'")
                cursor.execute("SET statement_timeout TO '5000'")
        except Exception:
            # если коннекта ещё нет — сработают options из DATABASES
            pass
