from django.db import migrations
from django.db.models import Count, Sum


def rebuild_contract_metrics(apps, _schema_editor):
    BusinessDirection = apps.get_model("analytics", "BusinessDirection")
    CrmDeal = apps.get_model("analytics", "CrmDeal")
    ManagerDailyMetric = apps.get_model("analytics", "ManagerDailyMetric")

    ro_direction_ids = list(
        BusinessDirection.objects.filter(code="ro").values_list("id", flat=True)
    )
    if not ro_direction_ids:
        return

    ManagerDailyMetric.objects.filter(direction_id__in=ro_direction_ids).update(
        contracts=0,
        contract_amount=0,
    )

    contract_rows = (
        CrmDeal.objects.filter(
            contract_date__isnull=False,
            assigned_by_id__isnull=False,
            direction_id__in=ro_direction_ids,
        )
        .values("contract_date", "assigned_by_id", "direction_id")
        .annotate(
            contracts=Count("id"),
            contract_amount=Sum("contract_amount"),
        )
    )

    for row in contract_rows.iterator(chunk_size=1000):
        metric, created = ManagerDailyMetric.objects.get_or_create(
            metric_date=row["contract_date"],
            manager_id=row["assigned_by_id"],
            direction_id=row["direction_id"],
            defaults={
                "leads": 0,
                "target_leads": 0,
                "zz": 0,
                "contracts": row["contracts"],
                "contract_amount": row["contract_amount"] or 0,
            },
        )
        if not created:
            metric.contracts = row["contracts"]
            metric.contract_amount = row["contract_amount"] or 0
            metric.save(update_fields=["contracts", "contract_amount"])


class Migration(migrations.Migration):
    dependencies = [
        ("analytics", "0010_backfill_ro_contract_fields"),
    ]

    operations = [
        migrations.RunPython(rebuild_contract_metrics, migrations.RunPython.noop),
    ]
