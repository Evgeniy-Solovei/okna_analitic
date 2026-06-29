#!/usr/bin/env python3
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path
from uuid import uuid4


BASE_URL = "http://localhost:3000"
ADMIN_EMAIL = "admin@example.local"
ADMIN_PASSWORD = "demo-metabase-123"
COLLECTION_NAME = "Демо: эффективность менеджеров"
DATABASE_NAME = "Bitrix24 demo SQLite"

FIELD_DATE_ID = 77
FIELD_MANAGER_ID = 78
FIELD_DIRECTION_ID = 79


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

    def login(self):
        result = self.request(
            "POST",
            "/api/session",
            {"username": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
        )
        self.session = result["id"]


def native_tags():
    return {
        "period": {
            "id": str(uuid4()),
            "name": "period",
            "display-name": "Период",
            "type": "dimension",
            "dimension": ["field", FIELD_DATE_ID, {"base-type": "type/Date"}],
            "widget-type": "date/range",
            "required": False,
        },
        "manager": {
            "id": str(uuid4()),
            "name": "manager",
            "display-name": "Менеджер",
            "type": "dimension",
            "dimension": ["field", FIELD_MANAGER_ID, {"base-type": "type/Text"}],
            "widget-type": "category",
            "required": False,
        },
        "direction": {
            "id": str(uuid4()),
            "name": "direction",
            "display-name": "Направление",
            "type": "dimension",
            "dimension": ["field", FIELD_DIRECTION_ID, {"base-type": "type/Text"}],
            "widget-type": "category",
            "required": False,
        },
    }


FILTER_SQL = "WHERE {{period}} [[AND {{manager}}]] [[AND {{direction}}]]"


def card_payload(db_id, collection_id, name, query, display, settings=None):
    return {
        "name": name,
        "description": "Showcase-версия для презентации демо-модуля Metabase.",
        "collection_id": collection_id,
        "dataset_query": {
            "database": db_id,
            "type": "native",
            "native": {
                "query": query.strip(),
                "template-tags": native_tags(),
            },
        },
        "display": display,
        "visualization_settings": settings or {},
    }


def create_card(client, db_id, collection_id, name, query, display, settings=None):
    return client.request(
        "POST",
        "/api/card",
        card_payload(db_id, collection_id, name, query, display, settings),
    )["id"]


def get_database_id(client):
    databases = client.request("GET", "/api/database").get("data", [])
    for database in databases:
        if database.get("name") == DATABASE_NAME:
            return database["id"]
    raise RuntimeError(f"Database not found: {DATABASE_NAME}")


def get_collection_id(client):
    collections = client.request("GET", "/api/collection")
    for collection in collections:
        if collection.get("name") == COLLECTION_NAME:
            return collection["id"]
    raise RuntimeError(f"Collection not found: {COLLECTION_NAME}")


def make_mapping(parameter_id, card_id, tag_name):
    return {
        "parameter_id": parameter_id,
        "card_id": card_id,
        "target": ["dimension", ["template-tag", tag_name]],
    }


def main():
    client = MetabaseClient(BASE_URL)
    client.login()

    db_id = get_database_id(client)
    collection_id = get_collection_id(client)

    cards = [
        (
            "Лиды",
            f'SELECT SUM(leads) AS "Лиды" FROM v_manager_daily_metrics {FILTER_SQL};',
            "scalar",
            {},
            (0, 0, 4, 3),
        ),
        (
            "Целевые лиды",
            f'SELECT SUM(target_leads) AS "ЦЛ" FROM v_manager_daily_metrics {FILTER_SQL};',
            "scalar",
            {},
            (0, 4, 4, 3),
        ),
        (
            "ЗЗ",
            f'SELECT SUM(zz) AS "ЗЗ" FROM v_manager_daily_metrics {FILTER_SQL};',
            "scalar",
            {},
            (0, 8, 4, 3),
        ),
        (
            "Конверсия",
            f'''
            SELECT ROUND(100.0 * SUM(zz) / NULLIF(SUM(target_leads), 0), 1) AS "Конверсия, %"
            FROM v_manager_daily_metrics
            {FILTER_SQL};
            ''',
            "scalar",
            {"scalar.suffix": "%"},
            (0, 12, 4, 3),
        ),
        (
            "Сумма договоров",
            f'''
            SELECT SUM(contract_amount) AS "Сумма договоров"
            FROM v_manager_daily_metrics
            {FILTER_SQL};
            ''',
            "scalar",
            {"scalar.prefix": "", "scalar.suffix": " ₽"},
            (0, 16, 4, 3),
        ),
        (
            "Средний чек",
            f'''
            SELECT ROUND(1.0 * SUM(contract_amount) / NULLIF(SUM(contracts), 0), 0) AS "Средний чек"
            FROM v_manager_daily_metrics
            {FILTER_SQL};
            ''',
            "scalar",
            {"scalar.suffix": " ₽"},
            (0, 20, 4, 3),
        ),
        (
            "Динамика продаж по дням",
            f'''
            SELECT
              metric_date AS "Дата",
              SUM(target_leads) AS "ЦЛ",
              SUM(zz) AS "ЗЗ",
              SUM(contracts) AS "Договоры",
              SUM(contract_amount) AS "Сумма договоров"
            FROM v_manager_daily_metrics
            {FILTER_SQL}
            GROUP BY metric_date
            ORDER BY metric_date;
            ''',
            "line",
            {
                "graph.colors": ["#2A73CC", "#34A853", "#F6A623", "#7E57C2"],
                "graph.dimensions": ["Дата"],
                "graph.metrics": ["ЦЛ", "ЗЗ", "Договоры", "Сумма договоров"],
                "graph.x_axis.title_text": "Дата",
                "graph.y_axis.title_text": "Количество",
            },
            (3, 0, 24, 8),
        ),
        (
            "Конверсия по менеджерам",
            f'''
            SELECT
              manager AS "Менеджер",
              ROUND(100.0 * SUM(zz) / NULLIF(SUM(target_leads), 0), 1) AS "Конверсия, %"
            FROM v_manager_daily_metrics
            {FILTER_SQL}
            GROUP BY manager
            ORDER BY "Конверсия, %" DESC;
            ''',
            "bar",
            {
                "graph.colors": ["#2A73CC"],
                "graph.dimensions": ["Менеджер"],
                "graph.metrics": ["Конверсия, %"],
                "graph.x_axis.title_text": "Менеджер",
                "graph.y_axis.title_text": "Конверсия, %",
            },
            (11, 0, 12, 7),
        ),
        (
            "Сумма договоров по менеджерам",
            f'''
            SELECT
              manager AS "Менеджер",
              SUM(contract_amount) AS "Сумма договоров"
            FROM v_manager_daily_metrics
            {FILTER_SQL}
            GROUP BY manager
            ORDER BY "Сумма договоров" DESC;
            ''',
            "bar",
            {
                "graph.colors": ["#34A853"],
                "graph.dimensions": ["Менеджер"],
                "graph.metrics": ["Сумма договоров"],
                "graph.x_axis.title_text": "Менеджер",
            },
            (11, 12, 12, 7),
        ),
        (
            "Лидерборд менеджеров",
            f'''
            SELECT
              manager AS "Менеджер",
              SUM(target_leads) AS "ЦЛ",
              SUM(zz) AS "ЗЗ",
              ROUND(100.0 * SUM(zz) / NULLIF(SUM(target_leads), 0), 1) AS "Конверсия, %",
              SUM(contracts) AS "Договоры",
              SUM(contract_amount) AS "Сумма договоров",
              ROUND(1.0 * SUM(contract_amount) / NULLIF(SUM(contracts), 0), 0) AS "Средний чек"
            FROM v_manager_daily_metrics
            {FILTER_SQL}
            GROUP BY manager
            ORDER BY "Сумма договоров" DESC;
            ''',
            "table",
            {"table.pivot": False},
            (18, 0, 16, 7),
        ),
        (
            "Направления",
            f'''
            SELECT
              direction AS "Направление",
              SUM(leads) AS "Лиды",
              SUM(target_leads) AS "ЦЛ",
              SUM(zz) AS "ЗЗ",
              ROUND(100.0 * SUM(zz) / NULLIF(SUM(target_leads), 0), 1) AS "Конверсия, %",
              SUM(contract_amount) AS "Сумма договоров"
            FROM v_manager_daily_metrics
            {FILTER_SQL}
            GROUP BY direction
            ORDER BY "Сумма договоров" DESC;
            ''',
            "table",
            {},
            (18, 16, 8, 7),
        ),
    ]

    card_ids = []
    for name, query, display, settings, _layout in cards:
        card_ids.append(create_card(client, db_id, collection_id, name, query, display, settings))

    dashboard = client.request(
        "POST",
        "/api/dashboard",
        {
            "name": "Эффективность менеджеров",
            "description": "Презентационная версия демо-дашборда: KPI, динамика, сравнение менеджеров и рабочие фильтры.",
            "collection_id": collection_id,
            "width": "full",
            "parameters": [
                {
                    "id": "period",
                    "name": "Период",
                    "slug": "period",
                    "type": "date/range",
                    "sectionId": "date",
                },
                {
                    "id": "manager",
                    "name": "Менеджер",
                    "slug": "manager",
                    "type": "string/=",
                    "sectionId": "string",
                    "isMultiSelect": True,
                },
                {
                    "id": "direction",
                    "name": "Направление",
                    "slug": "direction",
                    "type": "string/=",
                    "sectionId": "string",
                    "isMultiSelect": True,
                },
            ],
        },
    )
    dashboard_id = dashboard["id"]

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

    client.request(
        "PUT",
        f"/api/dashboard/{dashboard_id}/cards",
        {
            "cards": dashcards,
            "tabs": [],
        },
    )

    print(f"Showcase dashboard: {BASE_URL}/dashboard/{dashboard_id}")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"Build failed: {exc}", file=sys.stderr)
        sys.exit(1)
