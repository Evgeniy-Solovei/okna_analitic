import time
from datetime import datetime, timedelta
from urllib.parse import urlencode

import jwt
from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.db import connection
from django.db.models import Count, Q, Sum
from django.db.models.functions import ExtractHour
from django.http import JsonResponse
from django.shortcuts import render
from django.utils import timezone

from .models import BusinessDirection, CrmDeal, CrmLead, CrmUser, DealFirstZZ, ManagerDailyMetric
from .services import bitrix_datetime, get_sync_cursor, parse_bitrix_datetime, run_bitrix24_sync, set_sync_cursor


SYNC_LOCK_ID = 24062026


def _try_advisory_lock() -> bool:
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_try_advisory_lock(%s)", [SYNC_LOCK_ID])
        return bool(cursor.fetchone()[0])


def _release_advisory_lock():
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_advisory_unlock(%s)", [SYNC_LOCK_ID])


def _on_demand_sync_if_needed(force: bool = False) -> dict:
    if not settings.ON_DEMAND_SYNC_ENABLED:
        return {"skipped": True, "reason": "disabled"}

    now = timezone.now()
    if not get_sync_cursor("bitrix24.modified_at"):
        return {"skipped": True, "reason": "initial_sync_required"}

    last_value = get_sync_cursor("bitrix24.on_demand_last_at")
    last_at = parse_bitrix_datetime(last_value) if last_value else None
    min_interval = timedelta(seconds=settings.ON_DEMAND_SYNC_MIN_INTERVAL_SECONDS)

    if not force and last_at and now - last_at < min_interval:
        return {"skipped": True, "reason": "recent", "last_at": last_value}

    if not _try_advisory_lock():
        return {"skipped": True, "reason": "locked"}

    try:
        stats = run_bitrix24_sync(mode="incremental", source="bitrix24_on_demand")
        set_sync_cursor("bitrix24.on_demand_last_at", bitrix_datetime(now), {"stats": stats})
        return {"skipped": False, "stats": stats}
    finally:
        _release_advisory_lock()


def _metabase_dashboard_id() -> int:
    if settings.METABASE_EMBEDDING_DASHBOARD_ID:
        return int(settings.METABASE_EMBEDDING_DASHBOARD_ID)
    return int(settings.METABASE_DASHBOARD_PATH.rstrip("/").split("/")[-1])


def _metabase_embed_url() -> str:
    payload = {
        "resource": {"dashboard": _metabase_dashboard_id()},
        "params": {},
        "exp": round(time.time()) + 12 * 60 * 60,
    }
    token = jwt.encode(payload, settings.METABASE_EMBEDDING_SECRET_KEY, algorithm="HS256")
    return f"/embed/dashboard/{token}#bordered=false&titled=false"


def _parse_date_param(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(value).date()
    except ValueError:
        return None


def _ids_from_request(request, name):
    values = []
    for value in request.GET.getlist(name):
        values.extend(str(value).split(","))
    return [int(value) for value in values if str(value).isdigit()]


def _url_with(filters, **overrides):
    params = {}
    if filters["date_from"]:
        params["date_from"] = filters["date_from"].isoformat()
    if filters["date_to"]:
        params["date_to"] = filters["date_to"].isoformat()
    if filters["selected_date"]:
        params["date"] = filters["selected_date"].isoformat()
    if filters["manager_ids"]:
        params["manager"] = filters["manager_ids"]
    if filters["direction_ids"]:
        params["direction"] = filters["direction_ids"]
    if filters.get("detail"):
        params["detail"] = filters["detail"]

    for key, value in overrides.items():
        if value in (None, "", []):
            params.pop(key, None)
        else:
            params[key] = value
    return "?" + urlencode(params, doseq=True)


def _metric_queryset(request):
    qs = ManagerDailyMetric.objects.select_related("manager", "direction")
    date_from = _parse_date_param(request.GET.get("date_from"))
    date_to = _parse_date_param(request.GET.get("date_to"))
    selected_date = _parse_date_param(request.GET.get("date"))
    manager_ids = _ids_from_request(request, "manager")
    direction_ids = _ids_from_request(request, "direction")
    detail = request.GET.get("detail") or ""

    if selected_date:
        qs = qs.filter(metric_date=selected_date)
    else:
        if not date_from and not date_to:
            today = timezone.localdate()
            date_from = today.replace(day=1)
            date_to = today
        if date_from:
            qs = qs.filter(metric_date__gte=date_from)
        if date_to:
            qs = qs.filter(metric_date__lte=date_to)
    if manager_ids:
        qs = qs.filter(manager_id__in=manager_ids)
    if direction_ids:
        qs = qs.filter(direction_id__in=direction_ids)
    return qs, {
        "date_from": date_from,
        "date_to": date_to,
        "selected_date": selected_date,
        "manager_ids": manager_ids,
        "direction_ids": direction_ids,
        "detail": detail,
    }


def _sum_metrics(qs):
    totals = qs.aggregate(
        leads=Sum("leads"),
        target_leads=Sum("target_leads"),
        zz=Sum("zz"),
        contracts=Sum("contracts"),
        contract_amount=Sum("contract_amount"),
    )
    for key, value in totals.items():
        totals[key] = value or 0
    totals["conversion"] = round(float(totals["zz"]) * 100 / float(totals["target_leads"]), 1) if totals["target_leads"] else 0
    totals["avg_check"] = round(float(totals["contract_amount"]) / float(totals["contracts"])) if totals["contracts"] else 0
    return totals


def _bar_rows(rows, value_key, max_width=100):
    max_value = max([float(row[value_key] or 0) for row in rows] or [0])
    for row in rows:
        value = float(row[value_key] or 0)
        row["bar_width"] = round(value / max_value * max_width, 2) if max_value else 0
    return rows


def _dashboard_context(request):
    qs, filters = _metric_queryset(request)
    totals = _sum_metrics(qs)

    manager_rows = list(
        qs.values("manager_id", "manager__name")
        .annotate(
            leads=Sum("leads"),
            target_leads=Sum("target_leads"),
            zz=Sum("zz"),
            contracts=Sum("contracts"),
            contract_amount=Sum("contract_amount"),
        )
        .order_by("-contract_amount", "manager__name")
    )
    for row in manager_rows:
        row["conversion"] = round(float(row["zz"] or 0) * 100 / float(row["target_leads"] or 0), 1) if row["target_leads"] else 0
        row["url"] = _url_with(filters, manager=[row["manager_id"]])

    conversion_rows = sorted(manager_rows, key=lambda item: item["conversion"], reverse=True)
    conversion_rows = _bar_rows(conversion_rows, "conversion")
    amount_rows = _bar_rows(manager_rows.copy(), "contract_amount")

    direction_rows = list(
        qs.values("direction_id", "direction__name")
        .annotate(
            leads=Sum("leads"),
            target_leads=Sum("target_leads"),
            zz=Sum("zz"),
            contracts=Sum("contracts"),
            contract_amount=Sum("contract_amount"),
        )
        .order_by("direction__name")
    )
    for row in direction_rows:
        row["conversion"] = round(float(row["zz"] or 0) * 100 / float(row["target_leads"] or 0), 1) if row["target_leads"] else 0
        row["url"] = _url_with(filters, direction=[row["direction_id"]])

    selected_managers = list(CrmUser.objects.filter(id__in=filters["manager_ids"]).order_by("name"))
    selected_directions = list(BusinessDirection.objects.filter(id__in=filters["direction_ids"]).order_by("name"))
    selected_manager_title = _selection_title(selected_managers, "Все менеджеры")
    selected_direction_title = _selection_title(selected_directions, "Все направления")

    if filters["selected_date"]:
        daily_rows = _hourly_rows_for_selected_date(filters)
    else:
        daily_rows = list(
            qs.values("metric_date")
            .annotate(target_leads=Sum("target_leads"), zz=Sum("zz"), contracts=Sum("contracts"), contract_amount=Sum("contract_amount"))
            .order_by("metric_date")
        )
    daily_max = max([row["target_leads"] or 0 for row in daily_rows] + [row["zz"] or 0 for row in daily_rows] + [row["contracts"] or 0 for row in daily_rows] + [1])
    for row in daily_rows:
        row["target_height"] = round((row["target_leads"] or 0) / daily_max * 140, 2)
        row["zz_height"] = round((row["zz"] or 0) / daily_max * 140, 2)
        row["contracts_height"] = round((row["contracts"] or 0) / daily_max * 140, 2)
        row["url"] = _url_with(filters, date=row["metric_date"].isoformat(), date_from=None, date_to=None)

    base_detail_filters = Q()
    if filters["manager_ids"]:
        base_detail_filters &= Q(assigned_by_id__in=filters["manager_ids"])
    if filters["direction_ids"]:
        base_detail_filters &= Q(direction_id__in=filters["direction_ids"])

    lead_detail_filters = base_detail_filters
    deal_detail_filters = base_detail_filters
    contract_detail_filters = base_detail_filters
    first_zz_filters = Q()
    if filters["manager_ids"]:
        first_zz_filters &= Q(assigned_by_id__in=filters["manager_ids"]) | Q(assigned_by__isnull=True, deal__assigned_by_id__in=filters["manager_ids"])
    if filters["direction_ids"]:
        first_zz_filters &= Q(deal__direction_id__in=filters["direction_ids"])

    if filters["selected_date"]:
        lead_detail_filters &= Q(created_time__date=filters["selected_date"])
        deal_detail_filters &= Q(created_time__date=filters["selected_date"])
        contract_detail_filters &= Q(contract_date=filters["selected_date"])
        first_zz_filters &= Q(first_zz_at__date=filters["selected_date"])
    else:
        if filters["date_from"]:
            lead_detail_filters &= Q(created_time__date__gte=filters["date_from"])
            deal_detail_filters &= Q(created_time__date__gte=filters["date_from"])
            contract_detail_filters &= Q(contract_date__gte=filters["date_from"])
            first_zz_filters &= Q(first_zz_at__date__gte=filters["date_from"])
        if filters["date_to"]:
            lead_detail_filters &= Q(created_time__date__lte=filters["date_to"])
            deal_detail_filters &= Q(created_time__date__lte=filters["date_to"])
            contract_detail_filters &= Q(contract_date__lte=filters["date_to"])
            first_zz_filters &= Q(first_zz_at__date__lte=filters["date_to"])

    detail = filters["detail"]
    details_enabled = bool(filters["manager_ids"] or filters["selected_date"] or detail)
    details = {}
    if details_enabled:
        details = {
            "leads": CrmLead.objects.select_related("assigned_by", "direction").filter(lead_detail_filters).order_by("-created_time")[:50],
            "deals": CrmDeal.objects.select_related("assigned_by", "direction", "stage").filter(deal_detail_filters).order_by("-created_time")[:50],
            "zz": DealFirstZZ.objects.select_related("deal", "assigned_by", "stage", "deal__assigned_by", "deal__direction").filter(first_zz_filters).order_by("-first_zz_at")[:50],
            "contracts": CrmDeal.objects.select_related("assigned_by", "direction", "stage").filter(contract_detail_filters, contract_date__isnull=False).order_by("-contract_date")[:50],
        }

    show_details = {
        "leads": detail in {"", "leads"},
        "target_leads": detail in {"", "target_leads", "conversion"},
        "zz": detail in {"", "zz", "conversion"},
        "contracts": detail in {"", "contracts", "avg_check", "contract_amount"},
    }
    detail_title = {
        "leads": "Лиды",
        "target_leads": "Целевые лиды",
        "zz": "ЗЗ",
        "conversion": "Конверсия",
        "contracts": "Договоры",
        "avg_check": "Средний чек",
        "contract_amount": "Сумма договоров",
    }.get(detail, "Детализация")

    chart_data = {
        "daily": [
            {
                "label": row.get("label") or row["metric_date"].strftime("%d.%m"),
                "date": row["metric_date"].isoformat(),
                "target_leads": int(row["target_leads"] or 0),
                "zz": int(row["zz"] or 0),
                "contracts": int(row["contracts"] or 0),
                "url": row["url"],
            }
            for row in daily_rows
        ],
        "conversion": [
            {
                "label": row["manager__name"],
                "value": float(row["conversion"] or 0),
                "url": row["url"],
            }
            for row in conversion_rows
        ],
        "amounts": [
            {
                "label": row["manager__name"],
                "value": float(row["contract_amount"] or 0),
                "url": row["url"],
            }
            for row in amount_rows
        ],
    }

    return {
        "totals": totals,
        "filters": filters,
        "managers": CrmUser.objects.filter(
            id__in=ManagerDailyMetric.objects.values_list("manager_id", flat=True).distinct()
        ).order_by("name"),
        "directions": BusinessDirection.objects.filter(
            id__in=ManagerDailyMetric.objects.values_list("direction_id", flat=True).distinct()
        ).order_by("name"),
        "selected_managers": selected_managers,
        "selected_directions": selected_directions,
        "selected_manager_title": selected_manager_title,
        "selected_direction_title": selected_direction_title,
        "conversion_rows": conversion_rows,
        "amount_rows": amount_rows,
        "direction_rows": direction_rows,
        "daily_rows": daily_rows,
        "chart_data": chart_data,
        "details_enabled": details_enabled,
        "detail_title": detail_title,
        "show_details": show_details,
        "details": details,
    }


def _selection_title(items, empty_title):
    if not items:
        return empty_title
    first = items[0].name
    if len(items) == 1:
        return first
    return f"{len(items)} выбрано: {first}"


def _hourly_rows_for_selected_date(filters):
    selected_date = filters["selected_date"]
    manager_ids = filters["manager_ids"]
    direction_ids = filters["direction_ids"]

    lead_filters = Q(created_time__date=selected_date)
    deal_filters = Q(created_time__date=selected_date)
    zz_filters = Q(first_zz_at__date=selected_date)
    contract_filters = Q(contract_date=selected_date)

    if manager_ids:
        lead_filters &= Q(assigned_by_id__in=manager_ids)
        deal_filters &= Q(assigned_by_id__in=manager_ids)
        zz_filters &= Q(assigned_by_id__in=manager_ids) | Q(assigned_by__isnull=True, deal__assigned_by_id__in=manager_ids)
        contract_filters &= Q(assigned_by_id__in=manager_ids)
    if direction_ids:
        lead_filters &= Q(direction_id__in=direction_ids)
        deal_filters &= Q(direction_id__in=direction_ids)
        zz_filters &= Q(deal__direction_id__in=direction_ids)
        contract_filters &= Q(direction_id__in=direction_ids)

    target_by_hour = {
        item["hour"]: item["count"]
        for item in CrmDeal.objects.filter(deal_filters).annotate(hour=ExtractHour("created_time")).values("hour").annotate(count=Count("id"))
    }
    zz_by_hour = {
        item["hour"]: item["count"]
        for item in DealFirstZZ.objects.filter(zz_filters).annotate(hour=ExtractHour("first_zz_at")).values("hour").annotate(count=Count("id"))
    }
    contracts_by_hour = {
        item["hour"]: item["count"]
        for item in CrmDeal.objects.filter(contract_filters, contract_date__isnull=False).annotate(hour=ExtractHour("created_time")).values("hour").annotate(count=Count("id"))
    }

    rows = []
    for hour in range(24):
        rows.append(
            {
                "metric_date": selected_date,
                "label": f"{hour:02d}:00",
                "target_leads": target_by_hour.get(hour, 0),
                "zz": zz_by_hour.get(hour, 0),
                "contracts": contracts_by_hour.get(hour, 0),
                "contract_amount": 0,
                "url": _url_with(filters, date=selected_date.isoformat()),
            }
        )
    return rows


@login_required
def dashboard_entry(request):
    force_sync = request.GET.get("force") == "1"
    if force_sync or not request.GET:
        _on_demand_sync_if_needed(force=force_sync)
    return render(request, "analytics/native_dashboard.html", _dashboard_context(request))


@login_required
def refresh_status(request):
    result = _on_demand_sync_if_needed(force=request.GET.get("force") == "1")
    return JsonResponse(result)
