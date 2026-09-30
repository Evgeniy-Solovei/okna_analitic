from __future__ import annotations

import logging
from collections import defaultdict
from datetime import date, datetime, timedelta
from decimal import Decimal
from itertools import islice
from typing import Any, Iterable

logger = logging.getLogger(__name__)


from django.conf import settings
from django.db import connection, transaction
from django.db.models import Sum
from django.utils import timezone

from .bitrix import BitrixClient
from .models import (
    BusinessDirection,
    CrmDeal,
    CrmLead,
    CrmPipeline,
    CrmStage,
    CrmUser,
    DealFirstZZ,
    DealStageEvent,
    ManagerDailyMetric,
    MeasurerDailyMetric,
    SyncCursor,
    SyncRun,
)

# Единый lock для celery / on-demand / management-команд — без параллельных sync.
SYNC_LOCK_ID = 24062026


def _try_advisory_lock() -> bool:
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_try_advisory_lock(%s)", [SYNC_LOCK_ID])
        return bool(cursor.fetchone()[0])


def _release_advisory_lock() -> None:
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_advisory_unlock(%s)", [SYNC_LOCK_ID])


def parse_bitrix_datetime(value: str | None):
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def parse_bitrix_date(value: str | None):
    if not value:
        return None
    return parse_bitrix_datetime(value).date() if "T" in value else date.fromisoformat(value[:10])


def decimal_from_bitrix(value: Any) -> Decimal:
    if value in (None, ""):
        return Decimal("0")
    return Decimal(str(value).replace(",", "."))


def _unwrap_bitrix_scalar(value: Any):
    """Bitrix employee/list UF часто приходит как ['123'] или вложенный список."""
    while isinstance(value, (list, tuple)):
        if not value:
            return None
        value = value[0]
    if value in (None, "", 0, "0"):
        return None
    return value


def contract_date_from_deal(raw: dict[str, Any]):
    """Read the contract date from the field used by the deal's funnel."""
    default_field = settings.BITRIX24["DEAL_CONTRACT_DATE_FIELD"]
    ro_field = settings.BITRIX24["RO_DEAL_CONTRACT_DATE_FIELD"]
    selected_field = (
        ro_field
        if str(raw.get("CATEGORY_ID", "0")) == str(settings.BITRIX24["RO_PIPELINE_ID"])
        else default_field
    )
    value = raw.get(selected_field) if selected_field else None
    if not value and selected_field != default_field and default_field:
        value = raw.get(default_field)
    return parse_bitrix_date(_unwrap_bitrix_scalar(value))


def _is_ro_deal(raw: dict[str, Any]) -> bool:
    return str(raw.get("CATEGORY_ID", "0")) == str(settings.BITRIX24["RO_PIPELINE_ID"])


def measure_datetime_from_deal(raw: dict[str, Any]):
    """Дата/время замера: отдельные UF для Панорамы и РО."""
    default_field = settings.BITRIX24.get("DEAL_MEASURE_DATETIME_FIELD")
    ro_field = settings.BITRIX24.get("RO_DEAL_MEASURE_DATETIME_FIELD")
    selected_field = ro_field if _is_ro_deal(raw) else default_field
    value = raw.get(selected_field) if selected_field else None
    if not value and selected_field != default_field and default_field:
        value = raw.get(default_field)
    return parse_bitrix_datetime(_unwrap_bitrix_scalar(value))


def measurer_from_deal(raw: dict[str, Any]):
    """Замерщик: отдельные UF для Панорамы и РО, с fallback."""
    default_field = settings.BITRIX24.get("DEAL_MEASURER_FIELD")
    ro_field = settings.BITRIX24.get("RO_DEAL_MEASURER_FIELD")
    selected_field = ro_field if _is_ro_deal(raw) else default_field
    value = raw.get(selected_field) if selected_field else None
    if not value and selected_field != default_field and default_field:
        value = raw.get(default_field)
    value = _unwrap_bitrix_scalar(value)
    if not value:
        return None
    try:
        return CrmUser.objects.filter(bitrix_id=int(value)).first()
    except (TypeError, ValueError):
        return None


def bitrix_datetime(value: datetime) -> str:
    return value.astimezone(timezone.get_current_timezone()).replace(microsecond=0).isoformat()


def get_sync_cursor(name: str):
    cursor = SyncCursor.objects.filter(name=name).first()
    return cursor.value if cursor else None


def set_sync_cursor(name: str, value: str, payload: dict[str, Any] | None = None):
    SyncCursor.objects.update_or_create(
        name=name,
        defaults={"value": value, "payload": payload or {}},
    )


def incremental_modified_from(cursor_name: str, overlap_minutes: int = 10) -> str | None:
    value = get_sync_cursor(cursor_name)
    if not value:
        return None
    parsed = parse_bitrix_datetime(value)
    if not parsed:
        return value
    return bitrix_datetime(parsed - timedelta(minutes=overlap_minutes))


def _changed_deals_metric_start(run_started_at) -> date:
    """Нижняя граница пересчёта метрик: 30 дней + даты затронутых сделок."""
    default_start = timezone.localdate() - timedelta(days=30)
    earliest = default_start
    qs = CrmDeal.objects.filter(updated_at__gte=run_started_at).only(
        "created_time", "contract_date", "measure_scheduled_at"
    )
    for deal in qs.iterator(chunk_size=500):
        if deal.created_time:
            earliest = min(earliest, timezone.localtime(deal.created_time).date())
        if deal.contract_date:
            earliest = min(earliest, deal.contract_date)
        if deal.measure_scheduled_at:
            earliest = min(earliest, timezone.localtime(deal.measure_scheduled_at).date())
    return earliest


def run_bitrix24_sync(mode: str = "incremental", skip_history: bool = False, source: str = "bitrix24") -> dict[str, Any]:
    if mode not in {"full", "incremental"}:
        raise ValueError("mode must be 'full' or 'incremental'")

    if not _try_advisory_lock():
        logger.info("Bitrix sync skipped: advisory lock busy (source=%s mode=%s)", source, mode)
        return {"skipped": True, "reason": "locked", "source": source, "mode": mode}

    run_started_at = timezone.now()
    run = SyncRun.objects.create(source=source)
    stats: dict[str, Any] = {}
    try:
        # Фон может работать долго; веб при этом ограничен statement_timeout middleware.
        with connection.cursor() as cursor:
            cursor.execute("SET statement_timeout TO '600000'")

        client = BitrixClient.from_settings()
        stats["users"] = sync_users(client)
        stats.update(sync_pipelines_and_stages(client))

        modified_from = incremental_modified_from("bitrix24.modified_at") if mode == "incremental" else None
        stats["mode"] = mode
        stats["modified_from"] = modified_from
        stats["previous_cursor"] = get_sync_cursor("bitrix24.modified_at")

        stats["leads"] = sync_leads(client, modified_from=modified_from)
        stats["deals"] = sync_deals(client, modified_from=modified_from)

        # Reconcile удалений — только full. На инкременте кладёт Postgres и веб.
        if mode == "full":
            stats["reconciled_deleted_deals"] = reconcile_deleted_deals(client)
            set_sync_cursor("bitrix24.last_reconcile_at", bitrix_datetime(run_started_at))
        else:
            stats["reconciled_deleted_deals"] = 0
            stats["reconcile_skipped"] = "incremental"

        changed_deal_ids = None
        if mode == "incremental":
            changed_deal_ids = list(
                CrmDeal.objects.filter(updated_at__gte=run_started_at).values_list("bitrix_id", flat=True)
            )
            stats["changed_deals_for_history"] = len(changed_deal_ids)

        # История стадий из Bitrix — только full (или явный skip_history=False на full).
        # Инкремент: только локальный first_zz по уже скачанным событиям.
        if mode == "full" and not skip_history:
            stats["stage_events"] = sync_deal_stage_history(client, deal_ids=None)
            stats["first_zz"] = rebuild_first_zz(deal_ids=None)
        elif mode == "incremental":
            stats["stage_events"] = 0
            stats["history_skipped"] = "incremental"
            stats["first_zz"] = rebuild_first_zz(deal_ids=changed_deal_ids)
        else:
            stats["stage_events"] = 0
            stats["first_zz"] = 0

        if mode == "incremental":
            # Если сделки не менялись — метрики не трогаем (веб не конкурирует с записью).
            if changed_deal_ids:
                metric_start = _changed_deals_metric_start(run_started_at)
                stats["metric_start"] = metric_start.isoformat()
                stats["daily_metrics"] = rebuild_manager_daily_metrics(start_date=metric_start)
                stats["measurer_daily_metrics"] = rebuild_measurer_daily_metrics(start_date=metric_start)
            else:
                stats["daily_metrics"] = 0
                stats["measurer_daily_metrics"] = 0
                stats["metrics_skipped"] = "no_changed_deals"
        else:
            stats["daily_metrics"] = rebuild_manager_daily_metrics()
            stats["measurer_daily_metrics"] = rebuild_measurer_daily_metrics()

        set_sync_cursor(
            "bitrix24.modified_at",
            bitrix_datetime(run_started_at),
            {"last_success_run_id": run.id, "mode": mode, "source": source},
        )
    except Exception as exc:
        run.status = SyncRun.Status.FAILED
        run.finished_at = timezone.now()
        run.stats = stats
        run.error = str(exc)
        run.save(update_fields=["status", "finished_at", "stats", "error", "updated_at"])
        raise
    finally:
        try:
            with connection.cursor() as cursor:
                cursor.execute("SET statement_timeout TO DEFAULT")
        except Exception:
            pass
        _release_advisory_lock()

    run.status = SyncRun.Status.SUCCESS
    run.finished_at = timezone.now()
    run.stats = stats
    run.save(update_fields=["status", "finished_at", "stats", "updated_at"])
    return stats


def direction_from_code_or_name(value: str | None):
    if not value:
        return None
    normalized = str(value).strip().lower()
    if normalized in settings.BITRIX24["LEAD_PANORAMA_DIRECTION_VALUES"]:
        return BusinessDirection.objects.get(code=BusinessDirection.Code.PANORAMA)
    if normalized in settings.BITRIX24["LEAD_RO_DIRECTION_VALUES"]:
        return BusinessDirection.objects.get(code=BusinessDirection.Code.RO)
    return None


def upsert_user(raw: dict[str, Any]) -> CrmUser:
    bitrix_id = int(raw["ID"])
    name = " ".join(part for part in [raw.get("NAME"), raw.get("LAST_NAME")] if part).strip() or f"User {bitrix_id}"
    user, _ = CrmUser.objects.update_or_create(
        bitrix_id=bitrix_id,
        defaults={
            "name": name,
            "email": raw.get("EMAIL") or "",
            "is_active": raw.get("ACTIVE", True) in (True, "Y", "true", "1", 1),
            "raw": raw,
        },
    )
    return user


def sync_users(client: BitrixClient) -> int:
    count = 0
    for raw in client.list_all("user.get"):
        upsert_user(raw)
        count += 1
    return count


def sync_pipelines_and_stages(client: BitrixClient) -> dict[str, int]:
    stats = {"pipelines": 0, "stages": 0}
    panorama = BusinessDirection.objects.get(code=BusinessDirection.Code.PANORAMA)
    ro = BusinessDirection.objects.get(code=BusinessDirection.Code.RO)

    panorama_pipeline_id = str(settings.BITRIX24["PANORAMA_PIPELINE_ID"])
    ro_pipeline_id = str(settings.BITRIX24["RO_PIPELINE_ID"])
    b2b_pipeline_id = str(settings.BITRIX24["B2B_PIPELINE_ID"])

    for raw in client.list_all("crm.category.list", {"entityTypeId": 2}, result_key="categories"):
        bitrix_id = str(raw["id"])
        direction = None
        if bitrix_id == panorama_pipeline_id:
            direction = panorama
        elif bitrix_id == ro_pipeline_id:
            direction = ro
        elif bitrix_id == b2b_pipeline_id:
            direction = panorama
        CrmPipeline.objects.update_or_create(
            bitrix_id=bitrix_id,
            defaults={"name": raw.get("name") or bitrix_id, "direction": direction, "raw": raw},
        )
        stats["pipelines"] += 1

    zz_stage_ids = {
        settings.BITRIX24["PANORAMA_ZZ_STAGE_ID"],
        settings.BITRIX24["RO_ZZ_STAGE_ID"],
        settings.BITRIX24["B2B_ZZ_STAGE_ID"],
    }
    zn_stage_ids = {
        settings.BITRIX24["PANORAMA_ZN_STAGE_ID"],
        settings.BITRIX24["RO_ZN_STAGE_ID"],
        settings.BITRIX24["B2B_ZN_STAGE_ID"],
    }

    for pipeline in CrmPipeline.objects.all():
        stage_entity_id = "DEAL_STAGE" if pipeline.bitrix_id == "0" else f"DEAL_STAGE_{pipeline.bitrix_id}"
        statuses = client.call("crm.status.list", {"filter": {"ENTITY_ID": stage_entity_id}}) or []
        for raw in statuses:
            stage_id = raw["STATUS_ID"]
            CrmStage.objects.update_or_create(
                bitrix_id=stage_id,
                defaults={
                    "pipeline": pipeline,
                    "name": raw.get("NAME") or stage_id,
                    "sort": int(raw.get("SORT") or 0),
                    "is_zz": stage_id in zz_stage_ids,
                    "is_zn": stage_id in zn_stage_ids,
                    "is_success": raw.get("SEMANTICS") == "S",
                    "raw": raw,
                },
            )
            stats["stages"] += 1

    _sync_deal_directions_from_pipelines()
    return stats


def _sync_deal_directions_from_pipelines() -> int:
    updated = 0
    for pipeline in CrmPipeline.objects.exclude(direction__isnull=True):
        updated += CrmDeal.objects.filter(pipeline=pipeline).exclude(direction_id=pipeline.direction_id).update(
            direction_id=pipeline.direction_id
        )
    return updated


def ensure_b2b_integrity() -> bool:
    b2b_pipeline_id = settings.BITRIX24.get("B2B_PIPELINE_ID")
    panorama = BusinessDirection.objects.filter(code=BusinessDirection.Code.PANORAMA).first()
    if not b2b_pipeline_id or not panorama:
        return False

    pipeline = CrmPipeline.objects.filter(bitrix_id=str(b2b_pipeline_id)).first()
    if not pipeline:
        return False

    changed = False
    if pipeline.direction_id != panorama.id:
        pipeline.direction = panorama
        pipeline.save(update_fields=["direction", "updated_at"])
        changed = True

    updated_deals = CrmDeal.objects.filter(pipeline=pipeline).exclude(direction_id=panorama.id).update(
        direction_id=panorama.id
    )
    if updated_deals:
        changed = True

    b2b_direction = BusinessDirection.objects.filter(code=BusinessDirection.Code.B2B).first()
    if b2b_direction:
        migrated = CrmDeal.objects.filter(direction=b2b_direction).update(direction_id=panorama.id)
        if migrated:
            changed = True
        if ManagerDailyMetric.objects.filter(direction=b2b_direction).exists():
            ManagerDailyMetric.objects.filter(direction=b2b_direction).delete()
            changed = True
        if MeasurerDailyMetric.objects.filter(direction=b2b_direction).exists():
            MeasurerDailyMetric.objects.filter(direction=b2b_direction).delete()
            changed = True

        if b2b_direction.is_active:
            b2b_direction.is_active = False
            b2b_direction.save(update_fields=["is_active", "updated_at"])

    if changed:
        rebuild_manager_daily_metrics()
        rebuild_measurer_daily_metrics()
    return changed


def sync_leads(client: BitrixClient, modified_from: str | None = None) -> int:
    direction_field = settings.BITRIX24["LEAD_DIRECTION_FIELD"]
    payload = {
        "select": ["*", "UF_*"],
        "order": {"ID": "ASC"},
    }
    if modified_from:
        payload["filter"] = {">=DATE_MODIFY": modified_from}

    count = 0
    for raw in client.list_all("crm.lead.list", payload):
        assigned_by = CrmUser.objects.filter(bitrix_id=raw.get("ASSIGNED_BY_ID")).first()
        direction = direction_from_code_or_name(raw.get(direction_field)) if direction_field else None
        CrmLead.objects.update_or_create(
            bitrix_id=int(raw["ID"]),
            defaults={
                "title": raw.get("TITLE") or "",
                "status_id": raw.get("STATUS_ID") or "",
                "created_time": parse_bitrix_datetime(raw.get("DATE_CREATE")) or timezone.now(),
                "assigned_by": assigned_by,
                "direction": direction,
                "source_id": raw.get("SOURCE_ID") or "",
                "raw": raw,
            },
        )
        count += 1
    return count


def sync_deals(client: BitrixClient, modified_from: str | None = None) -> int:
    contract_number_field = settings.BITRIX24["DEAL_CONTRACT_NUMBER_FIELD"]
    contract_amount_field = settings.BITRIX24["DEAL_CONTRACT_AMOUNT_FIELD"]
    payload = {
        "select": ["*", "UF_*"],
        "order": {"ID": "ASC"},
    }
    if modified_from:
        payload["filter"] = {">=DATE_MODIFY": modified_from}

    count = 0
    for raw in client.list_all("crm.deal.list", payload):
        pipeline = CrmPipeline.objects.filter(bitrix_id=str(raw.get("CATEGORY_ID", "0"))).first()
        stage = CrmStage.objects.filter(bitrix_id=raw.get("STAGE_ID")).first()
        assigned_by = CrmUser.objects.filter(bitrix_id=raw.get("ASSIGNED_BY_ID")).first()
        lead = CrmLead.objects.filter(bitrix_id=raw.get("LEAD_ID")).first() if raw.get("LEAD_ID") else None
        direction = pipeline.direction if pipeline else None
        CrmDeal.objects.update_or_create(
            bitrix_id=int(raw["ID"]),
            defaults={
                "title": raw.get("TITLE") or "",
                "pipeline": pipeline,
                "stage": stage,
                "lead": lead,
                "assigned_by": assigned_by,
                "direction": direction,
                "created_time": parse_bitrix_datetime(raw.get("DATE_CREATE")) or timezone.now(),
                "moved_time": parse_bitrix_datetime(raw.get("MOVED_TIME")),
                "contract_number": str(raw.get(contract_number_field) or "") if contract_number_field else "",
                "contract_date": contract_date_from_deal(raw),
                "contract_amount": decimal_from_bitrix(raw.get(contract_amount_field)),
                "measurer": measurer_from_deal(raw),
                "measure_scheduled_at": measure_datetime_from_deal(raw),
                "raw": raw,
            },
        )
        count += 1
    return count


def reconcile_deleted_deals(client: BitrixClient) -> int:
    """Finds deals in local DB that were deleted in Bitrix24 and removes them using fast batching."""
    live_bitrix_ids: set[int] = set()
    start = 0
    while True:
        commands = {
            f"c_{i}": f"crm.deal.list?select[]=ID&order[ID]=ASC&start={start + i * 50}"
            for i in range(50)
        }
        batch_res = client.batch(commands)
        result_cmd = batch_res.get("result", {})

        fetched_count = 0
        last_reached = False
        for i in range(50):
            cmd_key = f"c_{i}"
            items = result_cmd.get(cmd_key, [])
            if not isinstance(items, list):
                break
            for raw in items:
                if "ID" in raw:
                    live_bitrix_ids.add(int(raw["ID"]))
                    fetched_count += 1
            if len(items) < 50:
                last_reached = True
                break

        if last_reached or fetched_count == 0:
            break
        start += 2500

    if not live_bitrix_ids:
        return 0

    # Не делаем exclude(bitrix_id__in=огромный_set) — Postgres может зависнуть на минуты/часы.
    local_ids = list(CrmDeal.objects.values_list("bitrix_id", flat=True))
    stale_ids = [bitrix_id for bitrix_id in local_ids if bitrix_id not in live_bitrix_ids]
    removed = 0
    for i in range(0, len(stale_ids), 500):
        chunk = stale_ids[i : i + 500]
        CrmDeal.objects.filter(bitrix_id__in=chunk).delete()
        removed += len(chunk)
    if removed:
        logger.info("Reconciling deleted deals: removed %s local deals", removed)
    return removed




def changed_deal_ids_since(modified_from: str | None) -> list[int]:
    qs = CrmDeal.objects.all()
    if modified_from:
        parsed = parse_bitrix_datetime(modified_from)
        if parsed:
            qs = qs.filter(raw__DATE_MODIFY__gte=modified_from)
    return list(qs.values_list("bitrix_id", flat=True))


def sync_deal_stage_history(client: BitrixClient, deal_ids: list[int] | None = None) -> int:
    deals = CrmDeal.objects.all()
    if deal_ids is not None:
        if not deal_ids:
            return 0
        deals = deals.filter(bitrix_id__in=deal_ids)

    def chunks(values: Iterable[int], size: int):
        iterator = iter(values)
        while batch := list(islice(iterator, size)):
            yield batch

    deals_by_bitrix_id = {deal.bitrix_id: deal for deal in deals.only("id", "bitrix_id", "assigned_by_id").iterator()}
    count = 0
    for batch_ids in chunks(deals_by_bitrix_id.keys(), 50):
        commands = {
            f"d{deal_id}": f"crm.stagehistory.list?entityTypeId=2&filter[OWNER_ID]={deal_id}&order[ID]=ASC"
            for deal_id in batch_ids
        }
        batch_result = client.batch(commands)
        results = batch_result.get("result", {})
        totals = batch_result.get("result_total", {})

        for key, result in results.items():
            deal_id = int(key[1:])
            deal = deals_by_bitrix_id[deal_id]
            events = result.get("items", result) if isinstance(result, dict) else result
            count += save_deal_stage_events(deal, events)

            if isinstance(result, dict) and int(totals.get(key) or 0) > len(result.get("items", [])):
                full_events = client.list_all(
                    "crm.stagehistory.list",
                    {"entityTypeId": 2, "filter": {"OWNER_ID": deal_id}, "order": {"ID": "ASC"}},
                    result_key="items",
                )
                count += save_deal_stage_events(deal, full_events)
    return count


def save_deal_stage_events(deal: CrmDeal, events) -> int:
    count = 0
    for raw in events:
        stage_id = raw.get("STAGE_ID") or raw.get("STATUS_ID") or raw.get("STAGE_SEMANTIC_ID") or ""
        changed_at = parse_bitrix_datetime(raw.get("CREATED_TIME") or raw.get("DATE_CREATE") or raw.get("DATE"))
        if not stage_id or not changed_at:
            continue
        stage = CrmStage.objects.filter(bitrix_id=stage_id).first()
        assigned_by = deal.assigned_by
        DealStageEvent.objects.update_or_create(
            deal=deal,
            stage_id_raw=stage_id,
            changed_at=changed_at,
            source_event_id=str(raw.get("ID") or ""),
            defaults={
                "stage": stage,
                "assigned_by": assigned_by,
                "raw": raw,
            },
        )
        count += 1
    return count


@transaction.atomic
def rebuild_first_zz(deal_ids: list[int] | None = None) -> int:
    zz_stages = set(CrmStage.objects.filter(is_zz=True).values_list("bitrix_id", flat=True))
    if not zz_stages:
        return 0

    if deal_ids is not None:
        if not deal_ids:
            return 0
        deals = list(CrmDeal.objects.filter(bitrix_id__in=deal_ids))
        count = 0
        for deal in deals:
            event = (
                DealStageEvent.objects.filter(deal=deal, stage_id_raw__in=zz_stages)
                .select_related("stage", "assigned_by")
                .order_by("changed_at", "id")
                .first()
            )
            if event:
                DealFirstZZ.objects.update_or_create(
                    deal=deal,
                    defaults={
                        "first_zz_at": event.changed_at,
                        "stage": event.stage,
                        "assigned_by": event.assigned_by or deal.assigned_by,
                        "source": "stage_history",
                    },
                )
                count += 1
            else:
                DealFirstZZ.objects.filter(deal=deal).delete()
        return count

    DealFirstZZ.objects.all().delete()
    count = 0
    for deal_id in DealStageEvent.objects.filter(stage_id_raw__in=zz_stages).values_list("deal_id", flat=True).distinct():
        event = (
            DealStageEvent.objects.filter(deal_id=deal_id, stage_id_raw__in=zz_stages)
            .select_related("deal", "stage", "assigned_by")
            .order_by("changed_at", "id")
            .first()
        )
        if not event:
            continue
        DealFirstZZ.objects.create(
            deal=event.deal,
            first_zz_at=event.changed_at,
            stage=event.stage,
            assigned_by=event.assigned_by or event.deal.assigned_by,
            source="stage_history",
        )
        count += 1
    return count



def _prune_stale_metric_rows(model, key_fields: tuple[str, str, str], keep_keys: set[tuple], start_date=None, end_date=None):
    """Удаляет только устаревшие ключи. Без DELETE всей таблицы — дашборд не блокируется."""
    qs = model.objects.all()
    if start_date:
        qs = qs.filter(**{f"{key_fields[0]}__gte": start_date})
    if end_date:
        qs = qs.filter(**{f"{key_fields[0]}__lte": end_date})

    stale_ids = []
    for row in qs.values_list("id", *key_fields).iterator(chunk_size=2000):
        row_id, key = row[0], row[1:]
        if key not in keep_keys:
            stale_ids.append(row_id)
            if len(stale_ids) >= 1000:
                model.objects.filter(id__in=stale_ids).delete()
                stale_ids = []
    if stale_ids:
        model.objects.filter(id__in=stale_ids).delete()


def rebuild_manager_daily_metrics(start_date: date | None = None, end_date: date | None = None) -> int:
    buckets: dict[tuple[date, int, int], dict[str, Any]] = defaultdict(
        lambda: {"leads": 0, "target_leads": 0, "zz": 0, "contracts": 0, "contract_amount": Decimal("0")}
    )

    lead_qs = CrmLead.objects.exclude(assigned_by__isnull=True)
    deal_target_qs = CrmDeal.objects.exclude(assigned_by__isnull=True).exclude(direction__isnull=True)
    deal_contract_qs = CrmDeal.objects.exclude(assigned_by__isnull=True).exclude(direction__isnull=True).exclude(contract_date__isnull=True)
    zz_qs = DealFirstZZ.objects.select_related("deal", "assigned_by", "deal__direction").exclude(assigned_by__isnull=True).exclude(deal__direction__isnull=True)

    if start_date:
        lead_qs = lead_qs.filter(created_time__date__gte=start_date)
        deal_target_qs = deal_target_qs.filter(created_time__date__gte=start_date)
        deal_contract_qs = deal_contract_qs.filter(contract_date__gte=start_date)
        zz_qs = zz_qs.filter(first_zz_at__date__gte=start_date)
    if end_date:
        lead_qs = lead_qs.filter(created_time__date__lte=end_date)
        deal_target_qs = deal_target_qs.filter(created_time__date__lte=end_date)
        deal_contract_qs = deal_contract_qs.filter(contract_date__lte=end_date)
        zz_qs = zz_qs.filter(first_zz_at__date__lte=end_date)

    lead_direction_from_deal = {}
    for lead_id, direction_id in (
        CrmDeal.objects.exclude(lead_id__isnull=True)
        .exclude(direction_id__isnull=True)
        .order_by("lead_id", "created_time", "id")
        .values_list("lead_id", "direction_id")
    ):
        lead_direction_from_deal.setdefault(lead_id, direction_id)

    for lead in lead_qs.only("id", "created_time", "assigned_by_id", "direction_id"):
        direction_id = lead.direction_id or lead_direction_from_deal.get(lead.id)
        if not direction_id:
            continue
        buckets[(lead.created_time.date(), lead.assigned_by_id, direction_id)]["leads"] += 1

    for deal in deal_target_qs.only("created_time", "assigned_by_id", "direction_id"):
        buckets[(deal.created_time.date(), deal.assigned_by_id, deal.direction_id)]["target_leads"] += 1

    for deal in deal_contract_qs.only("contract_date", "assigned_by_id", "direction_id", "contract_amount"):
        b = buckets[(deal.contract_date, deal.assigned_by_id, deal.direction_id)]
        b["contracts"] += 1
        b["contract_amount"] += deal.contract_amount

    for first_zz in zz_qs:
        buckets[(first_zz.first_zz_at.date(), first_zz.assigned_by_id, first_zz.deal.direction_id)]["zz"] += 1

    rows = [
        ManagerDailyMetric(
            metric_date=metric_date,
            manager_id=manager_id,
            direction_id=direction_id,
            **values,
        )
        for (metric_date, manager_id, direction_id), values in buckets.items()
    ]
    # Сначала upsert (дашборд продолжает читать старые/уже обновлённые строки),
    # потом точечно чистим хвосты — без DELETE всей таблицы в длинной транзакции.
    if rows:
        ManagerDailyMetric.objects.bulk_create(
            rows,
            batch_size=1000,
            update_conflicts=True,
            unique_fields=["metric_date", "manager_id", "direction_id"],
            update_fields=["leads", "target_leads", "zz", "contracts", "contract_amount"],
        )
    _prune_stale_metric_rows(
        ManagerDailyMetric,
        ("metric_date", "manager_id", "direction_id"),
        set(buckets.keys()),
        start_date=start_date,
        end_date=end_date,
    )
    return len(rows)


def rebuild_measurer_daily_metrics(start_date: date | None = None, end_date: date | None = None) -> int:
    """
    Замеры — по measure_scheduled_at (поле CRM «Дата и время замера» / «… РО»).
    Договоры и сумма — по contract_date (день заключения договора).
    Конверсия считается в отчёте как договоры / замеры.
    """
    buckets: dict[tuple[date, int, int], dict[str, Any]] = defaultdict(
        lambda: {"measures": 0, "contracts": 0, "contract_amount": Decimal("0")}
    )

    measure_qs = (
        CrmDeal.objects.exclude(measurer__isnull=True)
        .exclude(direction__isnull=True)
        .exclude(measure_scheduled_at__isnull=True)
    )
    contract_qs = (
        CrmDeal.objects.exclude(measurer__isnull=True)
        .exclude(direction__isnull=True)
        .exclude(contract_date__isnull=True)
    )

    if start_date:
        measure_qs = measure_qs.filter(measure_scheduled_at__date__gte=start_date)
        contract_qs = contract_qs.filter(contract_date__gte=start_date)
    if end_date:
        measure_qs = measure_qs.filter(measure_scheduled_at__date__lte=end_date)
        contract_qs = contract_qs.filter(contract_date__lte=end_date)

    for deal in measure_qs.only("measure_scheduled_at", "measurer_id", "direction_id"):
        measure_day = timezone.localtime(deal.measure_scheduled_at).date()
        buckets[(measure_day, deal.measurer_id, deal.direction_id)]["measures"] += 1

    for deal in contract_qs.only("contract_date", "measurer_id", "direction_id", "contract_amount"):
        bucket = buckets[(deal.contract_date, deal.measurer_id, deal.direction_id)]
        bucket["contracts"] += 1
        bucket["contract_amount"] += deal.contract_amount

    rows = [
        MeasurerDailyMetric(
            metric_date=metric_date,
            measurer_id=measurer_id,
            direction_id=direction_id,
            **values,
        )
        for (metric_date, measurer_id, direction_id), values in buckets.items()
    ]
    if rows:
        MeasurerDailyMetric.objects.bulk_create(
            rows,
            batch_size=1000,
            update_conflicts=True,
            unique_fields=["metric_date", "measurer_id", "direction_id"],
            update_fields=["measures", "contracts", "contract_amount"],
        )
    _prune_stale_metric_rows(
        MeasurerDailyMetric,
        ("metric_date", "measurer_id", "direction_id"),
        set(buckets.keys()),
        start_date=start_date,
        end_date=end_date,
    )
    return len(rows)

