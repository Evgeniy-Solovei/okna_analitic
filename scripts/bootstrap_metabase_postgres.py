#!/usr/bin/env python3
import json
import os
import sys
import time
import urllib.error
import urllib.request
from uuid import uuid4

from dotenv import load_dotenv


load_dotenv()

BASE_URL = os.getenv("METABASE_SITE_URL", "http://localhost:3000")
ADMIN_EMAIL = os.getenv("METABASE_ADMIN_EMAIL", "admin@example.local")
ADMIN_PASSWORD = os.getenv("METABASE_ADMIN_PASSWORD", "demo-metabase-123")
DATABASE_NAME = "Окна Панорама PostgreSQL"
COLLECTION_NAME = "Окна Панорама: эффективность менеджеров"
MAIN_DASHBOARD_NAME = "Эффективность менеджеров"
VIEW_NAME = "bi_manager_daily_metrics"


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

        req = urllib.request.Request(self.base_url + path, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=60) as response:
                body = response.read().decode("utf-8")
                if response.status not in expected:
                    raise RuntimeError(f"{method} {path} returned {response.status}: {body}")
                return json.loads(body) if body else {}
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
        raise RuntimeError(f"Metabase did not become ready at {self.base_url}")

    def setup_or_login(self):
        props = self.wait_until_ready()
        token = props.get("setup-token")
        if token:
            payload = {
                "token": token,
                "user": {
                    "first_name": "Local",
                    "last_name": "Admin",
                    "email": ADMIN_EMAIL,
                    "password": ADMIN_PASSWORD,
                    "password_confirm": ADMIN_PASSWORD,
                    "site_name": "Окна Панорама analytics",
                },
                "prefs": {
                    "site_name": "Окна Панорама analytics",
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

        result = self.request("POST", "/api/session", {"username": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
        self.session = result["id"]


def get_or_create_database(client: MetabaseClient) -> int:
    existing = client.request("GET", "/api/database").get("data", [])
    for database in existing:
        if database.get("name") == DATABASE_NAME:
            return database["id"]

    payload = {
        "engine": "postgres",
        "name": DATABASE_NAME,
        "details": {
            "host": os.getenv("POSTGRES_HOST", "localhost"),
            "port": int(os.getenv("POSTGRES_PORT", "5432")),
            "dbname": os.getenv("POSTGRES_DB"),
            "user": os.getenv("POSTGRES_USER"),
            "password": os.getenv("POSTGRES_PASSWORD"),
            "ssl": False,
            "tunnel-enabled": False,
            "advanced-options": False,
        },
        "is_full_sync": True,
        "is_on_demand": False,
        "auto_run_queries": True,
    }
    database = client.request("POST", "/api/database", payload)
    db_id = database["id"]
    client.request("POST", f"/api/database/{db_id}/sync_schema", {}, expected=(200, 202, 204))
    return db_id


def get_or_create_collection(client: MetabaseClient) -> int:
    collections = client.request("GET", "/api/collection")
    for collection in collections:
        if collection.get("name") == COLLECTION_NAME:
            return collection["id"]

    collection = client.request(
        "POST",
        "/api/collection",
        {
            "name": COLLECTION_NAME,
            "description": "Рабочие отчеты по данным Bitrix24.",
            "color": "#509EE3",
        },
    )
    return collection["id"]


def field_ids(client: MetabaseClient, db_id: int) -> dict[str, int]:
    for _ in range(60):
        metadata = client.request("GET", f"/api/database/{db_id}/metadata")
        for table in metadata.get("tables", []):
            if table.get("name") == VIEW_NAME:
                fields = {field["name"]: field["id"] for field in table.get("fields", [])}
                required = {"metric_date", "manager", "direction"}
                if required.issubset(fields):
                    return fields
        client.request("POST", f"/api/database/{db_id}/sync_schema", {}, expected=(200, 202, 204))
        time.sleep(3)
    raise RuntimeError(f"Metabase did not discover view {VIEW_NAME}")


def native_tags(fields: dict[str, int]):
    return {
        "period": {
            "id": str(uuid4()),
            "name": "period",
            "display-name": "Период",
            "type": "dimension",
            "dimension": ["field", fields["metric_date"], {"base-type": "type/Date"}],
            "widget-type": "date/range",
            "required": False,
        },
        "manager": {
            "id": str(uuid4()),
            "name": "manager",
            "display-name": "Менеджер",
            "type": "dimension",
            "dimension": ["field", fields["manager"], {"base-type": "type/Text"}],
            "widget-type": "category",
            "required": False,
        },
        "direction": {
            "id": str(uuid4()),
            "name": "direction",
            "display-name": "Направление",
            "type": "dimension",
            "dimension": ["field", fields["direction"], {"base-type": "type/Text"}],
            "widget-type": "category",
            "required": False,
        },
    }


FILTER_SQL = "WHERE {{period}} [[AND {{manager}}]] [[AND {{direction}}]]"


def create_card(client, db_id, collection_id, fields, name, query, display, settings=None):
    payload = {
        "name": name,
        "description": "Расчет по данным Bitrix24.",
        "collection_id": collection_id,
        "dataset_query": {
            "database": db_id,
            "type": "native",
            "native": {"query": query.strip(), "template-tags": native_tags(fields)},
        },
        "display": display,
        "visualization_settings": settings or {},
    }
    return client.request("POST", "/api/card", payload)["id"]


def make_mapping(parameter_id, card_id, tag_name):
    return {"parameter_id": parameter_id, "card_id": card_id, "target": ["dimension", ["template-tag", tag_name]]}


def get_or_create_dashboard(client: MetabaseClient, collection_id: int) -> int:
    items = client.request("GET", f"/api/collection/{collection_id}/items")
    for item in items.get("data", []):
        if item.get("model") == "dashboard" and item.get("name") == MAIN_DASHBOARD_NAME:
            return item["id"]

    dashboard = client.request(
        "POST",
        "/api/dashboard",
        {
            "name": MAIN_DASHBOARD_NAME,
            "description": "Рабочий дашборд по эффективности менеджеров.",
            "collection_id": collection_id,
            "width": "full",
            "parameters": [
                {"id": "period", "name": "Период", "slug": "period", "type": "date/range", "sectionId": "date"},
                {"id": "manager", "name": "Менеджер", "slug": "manager", "type": "string/=", "sectionId": "string", "isMultiSelect": True},
                {"id": "direction", "name": "Направление", "slug": "direction", "type": "string/=", "sectionId": "string", "isMultiSelect": True},
            ],
        },
    )
    return dashboard["id"]


def enable_dashboard_embedding(client: MetabaseClient, dashboard_id: int):
    dashboard = client.request("GET", f"/api/dashboard/{dashboard_id}")
    dashboard["enable_embedding"] = True
    dashboard["embedding_params"] = {}
    client.request("PUT", f"/api/dashboard/{dashboard_id}", dashboard)


def main():
    client = MetabaseClient(BASE_URL)
    client.setup_or_login()
    db_id = get_or_create_database(client)
    collection_id = get_or_create_collection(client)
    fields = field_ids(client, db_id)

    cards = [
        ("Лиды", f'SELECT SUM(leads) AS "Лиды" FROM {VIEW_NAME} {FILTER_SQL};', "scalar", {}, (0, 0, 4, 3)),
        ("Целевые лиды", f'SELECT SUM(target_leads) AS "ЦЛ" FROM {VIEW_NAME} {FILTER_SQL};', "scalar", {}, (0, 4, 4, 3)),
        ("ЗЗ", f'SELECT SUM(zz) AS "ЗЗ" FROM {VIEW_NAME} {FILTER_SQL};', "scalar", {}, (0, 8, 4, 3)),
        (
            "Конверсия",
            f'SELECT ROUND(100.0 * SUM(zz) / NULLIF(SUM(target_leads), 0), 1) AS "Конверсия, %" FROM {VIEW_NAME} {FILTER_SQL};',
            "scalar",
            {"scalar.suffix": "%"},
            (0, 12, 4, 3),
        ),
        (
            "Сумма договоров",
            f'SELECT SUM(contract_amount) AS "Сумма договоров" FROM {VIEW_NAME} {FILTER_SQL};',
            "scalar",
            {},
            (0, 16, 4, 3),
        ),
        (
            "Средний чек",
            f'SELECT ROUND(1.0 * SUM(contract_amount) / NULLIF(SUM(contracts), 0), 0) AS "Средний чек" FROM {VIEW_NAME} {FILTER_SQL};',
            "scalar",
            {},
            (0, 20, 4, 3),
        ),
        (
            "Динамика по дням",
            f"""
            SELECT metric_date AS "Дата", SUM(target_leads) AS "ЦЛ", SUM(zz) AS "ЗЗ", SUM(contracts) AS "Договоры"
            FROM {VIEW_NAME}
            {FILTER_SQL}
            GROUP BY metric_date
            ORDER BY metric_date;
            """,
            "line",
            {"graph.dimensions": ["Дата"], "graph.metrics": ["ЦЛ", "ЗЗ", "Договоры"]},
            (3, 0, 24, 8),
        ),
        (
            "Конверсия по менеджерам",
            f"""
            SELECT manager AS "Менеджер", ROUND(100.0 * SUM(zz) / NULLIF(SUM(target_leads), 0), 1) AS "Конверсия, %"
            FROM {VIEW_NAME}
            {FILTER_SQL}
            GROUP BY manager
            ORDER BY "Конверсия, %" DESC;
            """,
            "bar",
            {"graph.dimensions": ["Менеджер"], "graph.metrics": ["Конверсия, %"]},
            (11, 0, 12, 7),
        ),
        (
            "Сумма договоров по менеджерам",
            f"""
            SELECT manager AS "Менеджер", SUM(contract_amount) AS "Сумма договоров"
            FROM {VIEW_NAME}
            {FILTER_SQL}
            GROUP BY manager
            ORDER BY "Сумма договоров" DESC;
            """,
            "bar",
            {"graph.dimensions": ["Менеджер"], "graph.metrics": ["Сумма договоров"]},
            (11, 12, 12, 7),
        ),
        (
            "Направления",
            f"""
            SELECT direction AS "Направление", SUM(leads) AS "Лиды", SUM(target_leads) AS "ЦЛ", SUM(zz) AS "ЗЗ",
                   ROUND(100.0 * SUM(zz) / NULLIF(SUM(target_leads), 0), 1) AS "Конверсия, %",
                   SUM(contract_amount) AS "Сумма договоров"
            FROM {VIEW_NAME}
            {FILTER_SQL}
            GROUP BY direction
            ORDER BY "Сумма договоров" DESC;
            """,
            "table",
            {},
            (18, 0, 24, 7),
        ),
    ]

    card_ids = [
        create_card(client, db_id, collection_id, fields, name, query, display, settings)
        for name, query, display, settings, _layout in cards
    ]

    dashboard_id = get_or_create_dashboard(client, collection_id)

    dashcards = []
    for index, (card_id, (_name, _query, _display, _settings, layout)) in enumerate(zip(card_ids, cards), start=1):
        row, col, size_x, size_y = layout
        dashcards.append(
            {
                "id": -index,
                "card_id": card_id,
                "row": row,
                "col": col,
                "size_x": size_x,
                "size_y": size_y,
                "parameter_mappings": [
                    make_mapping("period", card_id, "period"),
                    make_mapping("manager", card_id, "manager"),
                    make_mapping("direction", card_id, "direction"),
                ],
                "series": [],
            }
        )

    client.request("PUT", f"/api/dashboard/{dashboard_id}/cards", {"cards": dashcards, "tabs": []})
    enable_dashboard_embedding(client, dashboard_id)
    print(f"Dashboard: {BASE_URL}/dashboard/{dashboard_id}")
    print(f"Login: {ADMIN_EMAIL}")
    print(f"Password: {ADMIN_PASSWORD}")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"Build failed: {exc}", file=sys.stderr)
        sys.exit(1)
