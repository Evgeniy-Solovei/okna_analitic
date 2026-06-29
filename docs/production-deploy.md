# Production deployment

## 1. Первый запуск на сервере

DNS:

```text
platform.oknapanorama.by A <SERVER_IP>
```

Подключение:

```bash
ssh root@<SERVER_IP>
```

Установка Docker на чистый Ubuntu/Debian сервер:

```bash
apt update
apt install -y ca-certificates curl git
install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
chmod a+r /etc/apt/keyrings/docker.asc
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" > /etc/apt/sources.list.d/docker.list
apt update
apt install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
```

Код проекта:

```bash
mkdir -p ~/panorama-analytics
cd ~/panorama-analytics
git clone https://github.com/Evgeniy-Solovei/okna_analitic.git .
```

Заполнить `.env` реальными значениями:

```bash
cp .env.example .env
nano .env
```

Обязательные значения:

```env
DJANGO_SECRET_KEY=...
DJANGO_DEBUG=false
DJANGO_ALLOWED_HOSTS=platform.oknapanorama.by,localhost,127.0.0.1
DJANGO_CSRF_TRUSTED_ORIGINS=https://platform.oknapanorama.by
APP_DOMAIN=platform.oknapanorama.by
METABASE_SITE_URL=https://platform.oknapanorama.by
METABASE_DASHBOARD_PATH=/dashboard/2
METABASE_EMBEDDING_DASHBOARD_ID=2
METABASE_EMBEDDING_SECRET_KEY=заменить-на-длинную-случайную-строку
MB_ENABLE_EMBEDDING=true
ON_DEMAND_SYNC_ENABLED=true
ON_DEMAND_SYNC_MIN_INTERVAL_SECONDS=60

POSTGRES_DB=panorama_analytics
POSTGRES_USER=panorama
POSTGRES_PASSWORD=...
POSTGRES_HOST=postgres
POSTGRES_PORT=5432

REDIS_URL=redis://redis:6379/0

BITRIX24_BASE_URL=https://oknapanorama.bitrix24.by
BITRIX24_WEBHOOK_URL=https://oknapanorama.bitrix24.by/rest/...

PANORAMA_PIPELINE_ID=0
RO_PIPELINE_ID=5
PANORAMA_ZZ_STAGE_ID=PREPAYMENT_INVOICE
RO_ZZ_STAGE_ID=C5:PREPAYMENT_INVOICE
PANORAMA_ZN_STAGE_ID=EXECUTING
RO_ZN_STAGE_ID=C5:EXECUTING

LEAD_DIRECTION_FIELD=UF_CRM_1781705104409
LEAD_PANORAMA_DIRECTION_VALUES=621,Панорама,panorama
LEAD_RO_DIRECTION_VALUES=623,Русские окна,РО,ro
DEAL_CONTRACT_DATE_FIELD=UF_CRM_1759322257791
DEAL_CONTRACT_AMOUNT_FIELD=OPPORTUNITY
```

Запуск контейнеров:

```bash
docker compose up -d --build postgres redis
docker compose up -d --build django celery celery-beat metabase caddy
```

Миграции:

```bash
docker compose exec django python manage.py migrate
docker compose exec django python manage.py createsuperuser
```

Проверка Bitrix webhook:

```bash
docker compose exec django python manage.py check_bitrix24
```

## 2. Первичная загрузка всех данных

Первичная загрузка лидов, сделок, пользователей, воронок, стадий:

```bash
docker compose exec django python manage.py sync_bitrix24 --full --skip-history
```

Полная загрузка истории стадий и расчет первого входа в `ЗЗ`:

```bash
docker compose exec django python manage.py sync_stage_history
```

Проверка агрегатов:

```bash
docker compose exec postgres psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "
select
  count(*) as rows,
  sum(leads) as leads,
  sum(target_leads) as target_leads,
  sum(zz) as zz,
  sum(contracts) as contracts,
  sum(contract_amount) as contract_amount
from bi_manager_daily_metrics;
"
```

## 3. Обновление данных

В проекте настроен `celery-beat`: задача `apps.analytics.tasks.sync_bitrix24_incremental` запускается один раз в 10 минут.

Домен тоже запускает быстрый on-demand sync: `https://platform.oknapanorama.by/` попадает в Django, Django делает incremental sync, если последний такой sync был больше `ON_DEMAND_SYNC_MIN_INTERVAL_SECONDS` секунд назад, и потом показывает встроенный Metabase dashboard без оболочки Metabase.

В production клиентский вход работает иначе: Django показывает собственную страницу с embedded Metabase dashboard. Поэтому клиент не видит боковые панели, кнопку создания отчетов, SQL-редактор, коллекции и администрирование Metabase.

Что делает sync каждые 10 минут:

- берет cursor `bitrix24.modified_at`;
- запрашивает из Bitrix только лиды и сделки с `DATE_MODIFY >= cursor - 10 минут`;
- обновляет локальные таблицы;
- подтягивает историю стадий только по измененным сделкам;
- пересчитывает `first_zz`;
- пересчитывает дневные метрики;
- сохраняет новый cursor.

Ручной запуск инкремента:

```bash
docker compose exec django python manage.py sync_bitrix24 --incremental
```

Если Celery не нужен, то вместо `celery` и `celery-beat` можно запускать cron на хосте:

```cron
*/10 * * * * cd ~/panorama-analytics && docker compose exec -T django python manage.py sync_bitrix24 --incremental >> /var/log/panorama-sync.log 2>&1
```

## 4. Metabase production setup

Metabase admin нужен только разработчику/администратору.

Заказчику нельзя выдавать admin-доступ. Иначе он сможет:

- редактировать SQL;
- удалять карточки;
- создавать новые вопросы;
- видеть таблицы;
- видеть админку;
- сломать dashboard.

Если клиенту все-таки создаются пользователи внутри Metabase, нужно сделать:

1. Создать группу `Viewers` или `Заказчик`.
2. Убрать лишние права у группы `All users`.
3. Для коллекции `Окна Панорама: эффективность менеджеров` дать группе заказчика только просмотр.
4. Для базы PostgreSQL запретить прямой доступ к таблицам для группы заказчика.
5. Создать пользователей клиента в этой группе.
6. Админский пользователь остается только у нас.

Клиенту открывать:

```text
https://platform.oknapanorama.by/
```

Публичные Metabase URL вида `/dashboard/<id>`, `/question/*`, `/collection/*`, `/auth/*` закрыты через Caddy.

`/dashboard/2` - это внутренний ID Metabase на текущем сервере. Для клиентского wrapper он задается в `.env` через `METABASE_EMBEDDING_DASHBOARD_ID=2`.

После включения embedded-режима пересобрать контейнеры:

```bash
docker compose up -d --build django celery celery-beat metabase caddy
docker compose exec django python manage.py migrate
```

Создать обычного пользователя для клиента в Django:

```bash
docker compose exec django python manage.py shell -c "from django.contrib.auth.models import User; User.objects.create_user('client', password='заменить-на-пароль')"
```

Админский интерфейс Metabase с публичного домена закрыт. Если разработчику нужно зайти в Metabase напрямую, открыть SSH tunnel с локального компьютера:

```bash
ssh -L 3000:127.0.0.1:3000 panorama@dashboard
```

Потом открыть локально:

```text
http://localhost:3000
```

## 5. Что нельзя убрать в прямом Metabase UI

Если пользователь залогинен в сам Metabase, часть оболочки Metabase остается:

- верхняя панель;
- поиск;
- профиль пользователя;
- часть навигации;
- стандартный стиль Metabase.

Это не баг проекта, а устройство Metabase.

В проекте уже используется отдельный Django wrapper и embedded dashboard. Это штатный способ показать только рабочий dashboard, без конструктора Metabase.

## 6. Светлая и темная тема

В Metabase есть настройки темы, но нормальный переключатель "светлая/темная" в клиентском dashboard как в SaaS-продукте лучше делать в нашем frontend.

Варианты:

- оставить Metabase theme как системную настройку;
- дать пользователям настраивать тему в профиле Metabase;
- сделать Django/React wrapper с собственным переключателем и embedded dashboard.
