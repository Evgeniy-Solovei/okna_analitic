#!/usr/bin/env python3
import calendar
import random
import sqlite3
from datetime import date, timedelta
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "data" / "bitrix24_demo.sqlite"

MANAGERS = [
    (1, "Анна Орлова"),
    (2, "Иван Петров"),
    (3, "Мария Соколова"),
    (4, "Дмитрий Волков"),
]

DIRECTIONS = [
    (1, "Основная воронка"),
    (2, "РО"),
]


def month_days(year: int, month: int):
    _, days = calendar.monthrange(year, month)
    for day in range(1, days + 1):
        yield date(year, month, day)


def main():
    random.seed(42)
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    if DB_PATH.exists():
        DB_PATH.unlink()

    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")

    conn.executescript(
        """
        CREATE TABLE managers (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            active INTEGER NOT NULL DEFAULT 1
        );

        CREATE TABLE directions (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL
        );

        CREATE TABLE manager_daily_metrics (
            metric_date DATE NOT NULL,
            manager_id INTEGER NOT NULL REFERENCES managers(id),
            direction_id INTEGER NOT NULL REFERENCES directions(id),
            leads INTEGER NOT NULL,
            target_leads INTEGER NOT NULL,
            zz_first_entries INTEGER NOT NULL,
            contracts INTEGER NOT NULL,
            contract_amount INTEGER NOT NULL,
            PRIMARY KEY (metric_date, manager_id, direction_id)
        );

        CREATE VIEW v_manager_daily_metrics AS
        SELECT
            mdm.metric_date,
            m.name AS manager,
            d.name AS direction,
            mdm.leads,
            mdm.target_leads,
            mdm.zz_first_entries AS zz,
            CASE
                WHEN mdm.target_leads = 0 THEN 0.0
                ELSE ROUND(1.0 * mdm.zz_first_entries / mdm.target_leads, 4)
            END AS conversion,
            mdm.contracts,
            mdm.contract_amount,
            CASE
                WHEN mdm.contracts = 0 THEN 0
                ELSE ROUND(1.0 * mdm.contract_amount / mdm.contracts, 0)
            END AS avg_check
        FROM manager_daily_metrics mdm
        JOIN managers m ON m.id = mdm.manager_id
        JOIN directions d ON d.id = mdm.direction_id;
        """
    )

    conn.executemany("INSERT INTO managers(id, name) VALUES (?, ?)", MANAGERS)
    conn.executemany("INSERT INTO directions(id, name) VALUES (?, ?)", DIRECTIONS)

    rows = []
    base_month = 6
    base_year = 2026

    for current_day in month_days(base_year, base_month):
        weekday = current_day.weekday()
        weekend_factor = 0.45 if weekday >= 5 else 1.0

        for manager_id, _manager in MANAGERS:
            manager_factor = {
                1: 1.18,
                2: 1.0,
                3: 0.92,
                4: 0.78,
            }[manager_id]

            for direction_id, _direction in DIRECTIONS:
                direction_factor = 1.0 if direction_id == 1 else 0.55
                leads = max(
                    0,
                    int(
                        random.gauss(13, 3)
                        * manager_factor
                        * direction_factor
                        * weekend_factor
                    ),
                )
                target_rate = 0.62 if direction_id == 1 else 0.72
                target_leads = int(leads * random.uniform(target_rate - 0.08, target_rate + 0.08))

                zz_rate = {
                    1: 0.45,
                    2: 0.37,
                    3: 0.34,
                    4: 0.28,
                }[manager_id]
                if direction_id == 2:
                    zz_rate += 0.08
                zz_first_entries = int(target_leads * random.uniform(zz_rate - 0.06, zz_rate + 0.08))

                contract_rate = {
                    1: 0.78,
                    2: 0.68,
                    3: 0.62,
                    4: 0.56,
                }[manager_id]
                contracts = int(zz_first_entries * random.uniform(contract_rate - 0.12, contract_rate + 0.1))

                avg_contract = random.randint(145_000, 265_000)
                if direction_id == 2:
                    avg_contract = random.randint(95_000, 155_000)
                contract_amount = contracts * avg_contract

                rows.append(
                    (
                        current_day.isoformat(),
                        manager_id,
                        direction_id,
                        leads,
                        target_leads,
                        zz_first_entries,
                        contracts,
                        contract_amount,
                    )
                )

    conn.executemany(
        """
        INSERT INTO manager_daily_metrics(
            metric_date,
            manager_id,
            direction_id,
            leads,
            target_leads,
            zz_first_entries,
            contracts,
            contract_amount
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        rows,
    )

    conn.commit()
    conn.close()

    print(f"Created demo SQLite database: {DB_PATH}")
    print(f"Rows: {len(rows)}")


if __name__ == "__main__":
    main()

