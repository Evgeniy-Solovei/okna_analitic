# Аналитический дашборд Окна Панорама

Проектная основа для внешней аналитической системы:

- Django backend;
- PostgreSQL как единый слой хранения;
- интеграция с Bitrix24;
- расчет первой даты входа сделки в `ЗЗ`;
- ежедневные метрики менеджеров;
- Metabase как BI-слой.

## Production через Docker

На сервере запускать через Docker Compose:

```bash
cp .env.example .env
# заполнить .env реальными доступами
docker compose up -d --build
docker compose exec django python manage.py migrate
docker compose exec django python manage.py createsuperuser
docker compose exec django python manage.py sync_bitrix24
```

Подробный production-порядок, первичный импорт, sync каждые 10 минут и настройка прав Metabase:
[docs/production-deploy.md](docs/production-deploy.md)

Проверка Django:

```text
http://localhost:8000/health/
```

Metabase:

```text
http://localhost:3000
```

## Что запросить у заказчика

Список доступов и решений: [docs/access-request.md](docs/access-request.md)

План реализации: [docs/development-plan.md](docs/development-plan.md)

## Локальная демонстрация Metabase

Цель этой заготовки: быстро показать, как может выглядеть дашборд "Эффективность менеджеров" в Metabase без Docker, Bitrix24 и PostgreSQL.

Демо использует:

- Metabase OSS как локальный `metabase.jar`;
- portable JRE 21 в папке `vendor/`;
- SQLite-файл `data/bitrix24_demo.sqlite` как временный источник демо-данных;
- Metabase application DB в `/tmp/bitrix-metabase-runtime/data/metabase-app/`.

Скрипт запуска копирует runtime-файлы в `/tmp/bitrix-metabase-runtime`, потому что Metabase JAR может падать при запуске из пути с пробелами.

В реальном этапе SQLite заменяется на PostgreSQL, а данные будут загружаться из Bitrix24 через Django-сервис синхронизации.

## Быстрый запуск

```bash
./scripts/download_runtime.sh
./scripts/create_demo_db.py
./scripts/start_metabase.sh
```

Когда в логах появится `Metabase Initialization COMPLETE`, в другом терминале:

```bash
./scripts/bootstrap_metabase.py
./scripts/build_showcase_dashboard.py
```

После этого открыть:

```text
http://localhost:3000/dashboard/4
```

Доступ для демо:

```text
Email: admin@example.local
Password: demo-metabase-123
```

## Что будет внутри

Скрипты создают два варианта:

- базовый технический дашборд;
- презентационный showcase-дашборд `Эффективность менеджеров`, который лучше использовать для показа.

Showcase содержит:

- отдельные KPI-карточки: лиды, целевые лиды, ЗЗ, конверсия, сумма договоров, средний чек;
- рабочие фильтры: период, менеджер, направление;
- широкая динамика по дням;
- сравнение менеджеров по конверсии, ЦЛ и сумме договоров;
- разрез по направлениям: общее, основная воронка, РО.

Важно: демо-таблица содержит поле `zz_first_entries`, которое имитирует утвержденное правило ТЗ: сделка учитывается в ЗЗ только по первой дате входа в этап.

Metabase Open Source не дает галерею дизайнерских шаблонов. Внешний вид настраивается через сетку, типы карточек, цвета графиков и тему интерфейса. Если нужен полностью брендированный красивый кабинет, его лучше делать отдельным Django/React-интерфейсом поверх той же PostgreSQL-модели.

## Ручной fallback

Если API-скрипт не сможет собрать дашборд из-за изменения API Metabase, Metabase все равно можно настроить вручную:

1. Войти в Metabase.
2. Admin settings -> Databases -> Add database.
3. Выбрать SQLite.
4. Filename: абсолютный путь к `data/bitrix24_demo.sqlite`.
5. Создать вопросы через SQL из `sql/metabase_questions.sql`.
