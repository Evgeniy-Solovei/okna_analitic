from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta
from decimal import Decimal
from itertools import islice
from typing import Any, Iterable

from django.conf import settings
from django.db import transaction
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
    SyncCursor,
    SyncRun,
)


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


def run_bitrix24_sync(mode: str = "incremental", skip_history: bool = False, source: str = "bitrix24") -> dict[str, Any]:
    if mode not in {"full", "incremental"}:
        raise ValueError("mode must be 'full' or 'incremental'")

    run_started_at = timezone.now()
    run = SyncRun.objects.create(source=source)
    stats: dict[str, Any] = {}
    try:
        client = BitrixClient.from_settings()
        stats["users"] = sync_users(client)
        stats.update(sync_pipelines_and_stages(client))

        modified_from = incremental_modified_from("bitrix24.modified_at") if mode == "incremental" else None
        stats["mode"] = mode
        stats["modified_from"] = modified_from
        stats["previous_cursor"] = get_sync_cursor("bitrix24.modified_at")

        stats["leads"] = sync_leads(client, modified_from=modified_from)
        stats["deals"] = sync_deals(client, modified_from=modified_from)

        changed_deal_ids = None
        if mode == "incremental":
            changed_deal_ids = list(CrmDeal.objects.filter(updated_at__gte=run_started_at).values_list("bitrix_id", flat=True))
            stats["changed_deals_for_history"] = len(changed_deal_ids)

        if not skip_history:
            stats["stage_events"] = sync_deal_stage_history(client, deal_ids=changed_deal_ids)
            stats["first_zz"] = rebuild_first_zz()
        stats["daily_metrics"] = rebuild_manager_daily_metrics()

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

    for raw in client.list_all("crm.category.list", {"entityTypeId": 2}, result_key="categories"):
        bitrix_id = str(raw["id"])
        direction = None
        if bitrix_id == panorama_pipeline_id:
            direction = panorama
        elif bitrix_id == ro_pipeline_id:
            direction = ro
        CrmPipeline.objects.update_or_create(
            bitrix_id=bitrix_id,
            defaults={"name": raw.get("name") or bitrix_id, "direction": direction, "raw": raw},
        )
        stats["pipelines"] += 1

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
                    "is_zz": stage_id in {settings.BITRIX24["PANORAMA_ZZ_STAGE_ID"], settings.BITRIX24["RO_ZZ_STAGE_ID"]},
                    "is_zn": stage_id in {settings.BITRIX24["PANORAMA_ZN_STAGE_ID"], settings.BITRIX24["RO_ZN_STAGE_ID"]},
                    "is_success": raw.get("SEMANTICS") == "S",
                    "raw": raw,
                },
            )
            stats["stages"] += 1
    return stats


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
    contract_date_field = settings.BITRIX24["DEAL_CONTRACT_DATE_FIELD"]
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
                "contract_date": parse_bitrix_date(raw.get(contract_date_field)) if contract_date_field else None,
                "contract_amount": decimal_from_bitrix(raw.get(contract_amount_field)),
                "raw": raw,
            },
        )
        count += 1
    return count


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
def rebuild_first_zz() -> int:
    DealFirstZZ.objects.all().delete()
    zz_stages = set(CrmStage.objects.filter(is_zz=True).values_list("bitrix_id", flat=True))
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


@transaction.atomic
def rebuild_manager_daily_metrics(start_date: date | None = None, end_date: date | None = None) -> int:
    qs = ManagerDailyMetric.objects.all()
    if start_date:
        qs = qs.filter(metric_date__gte=start_date)
    if end_date:
        qs = qs.filter(metric_date__lte=end_date)
    qs.delete()

    buckets: dict[tuple[date, int, int], dict[str, Any]] = defaultdict(
        lambda: {"leads": 0, "target_leads": 0, "zz": 0, "contracts": 0, "contract_amount": Decimal("0")}
    )

    lead_qs = CrmLead.objects.exclude(assigned_by__isnull=True)
    deal_qs = CrmDeal.objects.exclude(assigned_by__isnull=True).exclude(direction__isnull=True)
    zz_qs = DealFirstZZ.objects.select_related("deal", "assigned_by", "deal__direction").exclude(assigned_by__isnull=True).exclude(deal__direction__isnull=True)

    if start_date:
        lead_qs = lead_qs.filter(created_time__date__gte=start_date)
        deal_qs = deal_qs.filter(created_time__date__gte=start_date)
        zz_qs = zz_qs.filter(first_zz_at__date__gte=start_date)
    if end_date:
        lead_qs = lead_qs.filter(created_time__date__lte=end_date)
        deal_qs = deal_qs.filter(created_time__date__lte=end_date)
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

    for deal in deal_qs.only("created_time", "assigned_by_id", "direction_id", "contract_date", "contract_amount"):
        buckets[(deal.created_time.date(), deal.assigned_by_id, deal.direction_id)]["target_leads"] += 1
        if deal.contract_date:
            contract_bucket = buckets[(deal.contract_date, deal.assigned_by_id, deal.direction_id)]
            contract_bucket["contracts"] += 1
            contract_bucket["contract_amount"] += deal.contract_amount

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
    ManagerDailyMetric.objects.bulk_create(rows, batch_size=1000)
    return len(rows)
