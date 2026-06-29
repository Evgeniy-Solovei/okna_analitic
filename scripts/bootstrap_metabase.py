#!/usr/bin/env python3
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RUNTIME_ROOT = Path("/tmp/bitrix-metabase-runtime")
BASE_URL = "http://localhost:3000"
ADMIN_EMAIL = "admin@example.local"
ADMIN_PASSWORD = "demo-metabase-123"
SQLITE_PATH = RUNTIME_ROOT / "data" / "bitrix24_demo.sqlite"


class MetabaseClient:
    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")
        self.session = None

    def request(self, method, path, payload=None, expected=(200, 201, 202, 204)):
        data = None
        headers = {"Content-Type": "application/json"}
        if self.session:
            headers["X-Metabase-Session"] = self.session
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")

        req = urllib.request.Request(
            self.base_url + path,
            data=data,
            headers=headers,
            method=method,
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as response:
                body = response.read().decode("utf-8")
                if response.status not in expected:
                    raise RuntimeError(f"{method} {path} returned {response.status}: {body}")
                if not body:
                    return {}
                return json.loads(body)
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8")
            raise RuntimeError(f"{method} {path} returned {exc.code}: {body}") from exc

    def wait_until_ready(self):
        for _ in range(120):
            try:
                props = self.request("GET", "/api/session/properties")
                if props:
                    return props
            except Exception:
                time.sleep(2)
        raise RuntimeError("Metabase did not become ready at http://localhost:3000")

    def setup_or_login(self):
        props = self.wait_until_ready()
        token = props.get("setup-token")
        if token:
            payload = {
                "token": token,
                "user": {
                    "first_name": "Demo",
                    "last_name": "Admin",
                    "email": ADMIN_EMAIL,
                    "password": ADMIN_PASSWORD,
                    "password_confirm": ADMIN_PASSWORD,
                    "site_name": "Bitrix24 demo analytics",
                },
                "prefs": {
                    "site_name": "Bitrix24 demo analytics",
                    "site_locale": "ru",
                    "allow_tracking": False,
                },
            }
            try:
                result = self.request("POST", "/api/setup", payload)
                self.session = result.get("id") or result.get("session_id")
                if self.session:
                    return
            except RuntimeError as exc:
                if "403" not in str(exc):
                    raise

        result = self.request(
            "POST",
            "/api/session",
            {"username": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
        )
        self.session = result["id"]


def create_database(client: MetabaseClient) -> int:
    if not SQLITE_PATH.exists():
        raise RuntimeError("SQLite demo database is missing. Run ./scripts/create_demo_db.py first.")

    existing = client.request("GET", "/api/database")
    for db in existing.get("data", []):
        if db.get("name") == "Bitrix24 demo SQLite":
            return db["id"]

    payload = {
        "engine": "sqlite",
        "name": "Bitrix24 demo SQLite",
        "details": {
            "db": str(SQLITE_PATH),
            "advanced-options": False,
        },
        "is_full_sync": True,
        "is_on_demand": False,
        "auto_run_queries": True,
    }
    db = client.request("POST", "/api/database", payload)
    db_id = db["id"]
    try:
        client.request("POST", f"/api/database/{db_id}/sync_schema", {}, expected=(200, 202, 204))
    except Exception as exc:
        print(f"Schema sync was not started automatically: {exc}")
    return db_id


def create_collection(client: MetabaseClient) -> int:
    collections = client.request("GET", "/api/collection")
    for collection in collections:
        if collection.get("name") == "Демо: эффективность менеджеров":
            return collection["id"]

    result = client.request(
        "POST",
        "/api/collection",
        {
            "name": "Демо: эффективность менеджеров",
            "description": "Демо-графики по первому этапу аналитического дашборда.",
            "color": "#509EE3",
        },
    )
    return result["id"]


def create_card(client: MetabaseClient, db_id: int, collection_id: int, name: str, query: str, display: str):
    payload = {
        "name": name,
        "description": "Демо-вопрос для презентации Metabase по ТЗ.",
        "collection_id": collection_id,
        "dataset_query": {
            "database": db_id,
            "type": "native",
            "native": {
                "query": query,
                "template-tags": {},
            },
        },
        "display": display,
        "visualization_settings": {},
    }
    return client.request("POST", "/api/card", payload)["id"]


def create_dashboard(client: MetabaseClient, collection_id: int, card_ids: list[int]) -> int:
    result = client.request(
        "POST",
        "/api/dashboard",
        {
            "name": "Эффективность менеджеров",
            "description": "Демо-дашборд на искусственных данных: лиды, ЦЛ, ЗЗ, конверсия, договоры и сумма.",
            "collection_id": collection_id,
        },
    )
    dashboard_id = result["id"]

    layout = [
        (0, 0, 8, 4),
        (0, 8, 8, 4),
        (4, 0, 12, 5),
        (4, 12, 12, 5),
        (9, 0, 12, 5),
        (9, 12, 12, 5),
    ]

    dashcards = []
    for index, (card_id, (row, col, size_x, size_y)) in enumerate(zip(card_ids, layout), start=1):
        dashcards.append(
            {
                "id": -index,
                "card_id": card_id,
                "row": row,
                "col": col,
                "size_x": size_x,
                "size_y": size_y,
                "parameter_mappings": [],
                "series": [],
            }
        )

    client.request(
        "PUT",
        f"/api/dashboard/{dashboard_id}/cards",
        {
            "cards": dashcards,
            "tabs": [],
        },
    )

    return dashboard_id


def main():
    client = MetabaseClient(BASE_URL)
    client.setup_or_login()

    db_id = create_database(client)
    collection_id = create_collection(client)

    questions = [
        (
            "KPI: сводка за период",
            """
            SELECT
              SUM(leads) AS "Лиды",
              SUM(target_leads) AS "ЦЛ",
              SUM(zz) AS "ЗЗ",
              ROUND(100.0 * SUM(zz) / NULLIF(SUM(target_leads), 0), 1) AS "Конверсия, %",
              SUM(contracts) AS "Договоры",
              SUM(contract_amount) AS "Сумма договоров",
              ROUND(1.0 * SUM(contract_amount) / NULLIF(SUM(contracts), 0), 0) AS "Средний чек"
            FROM v_manager_daily_metrics;
            """,
            "table",
        ),
        (
            "Динамика ЦЛ, ЗЗ и договоров по дням",
            """
            SELECT
              metric_date AS "Дата",
              SUM(target_leads) AS "ЦЛ",
              SUM(zz) AS "ЗЗ",
              SUM(contracts) AS "Договоры"
            FROM v_manager_daily_metrics
            GROUP BY metric_date
            ORDER BY metric_date;
            """,
            "line",
        ),
        (
            "Конверсия по менеджерам",
            """
            SELECT
              manager AS "Менеджер",
              ROUND(100.0 * SUM(zz) / NULLIF(SUM(target_leads), 0), 1) AS "Конверсия, %"
            FROM v_manager_daily_metrics
            GROUP BY manager
            ORDER BY "Конверсия, %" DESC;
            """,
            "bar",
        ),
        (
            "Сумма договоров по менеджерам",
            """
            SELECT
              manager AS "Менеджер",
              SUM(contract_amount) AS "Сумма договоров"
            FROM v_manager_daily_metrics
            GROUP BY manager
            ORDER BY "Сумма договоров" DESC;
            """,
            "bar",
        ),
        (
            "Целевые лиды по менеджерам и направлениям",
            """
            SELECT
              manager AS "Менеджер",
              direction AS "Направление",
              SUM(target_leads) AS "ЦЛ"
            FROM v_manager_daily_metrics
            GROUP BY manager, direction
            ORDER BY manager, direction;
            """,
            "bar",
        ),
        (
            "Направления: общая эффективность",
            """
            SELECT
              direction AS "Направление",
              SUM(leads) AS "Лиды",
              SUM(target_leads) AS "ЦЛ",
              SUM(zz) AS "ЗЗ",
              ROUND(100.0 * SUM(zz) / NULLIF(SUM(target_leads), 0), 1) AS "Конверсия, %",
              SUM(contract_amount) AS "Сумма договоров"
            FROM v_manager_daily_metrics
            GROUP BY direction
            ORDER BY "Сумма договоров" DESC;
            """,
            "table",
        ),
    ]

    card_ids = [
        create_card(client, db_id, collection_id, name, query, display)
        for name, query, display in questions
    ]
    dashboard_id = create_dashboard(client, collection_id, card_ids)

    print("Metabase demo is ready.")
    print(f"Login: {ADMIN_EMAIL}")
    print(f"Password: {ADMIN_PASSWORD}")
    print(f"Dashboard: {BASE_URL}/dashboard/{dashboard_id}")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"Bootstrap failed: {exc}", file=sys.stderr)
        sys.exit(1)
