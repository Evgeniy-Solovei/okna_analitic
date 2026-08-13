from datetime import date

from django.db import migrations


RO_PIPELINE_ID = "5"
STANDARD_CONTRACT_DATE_FIELD = "UF_CRM_1759322257791"
RO_CONTRACT_DATE_FIELD = "UF_CRM_1784882995485"
CONTRACT_NUMBER_FIELD = "UF_CRM_1759759532794"


def parse_date(value):
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None


def backfill_ro_contract_fields(apps, _schema_editor):
    CrmDeal = apps.get_model("analytics", "CrmDeal")

    for deal in CrmDeal.objects.all().iterator(chunk_size=1000):
        raw = deal.raw or {}
        update_fields = []

        contract_number = str(raw.get(CONTRACT_NUMBER_FIELD) or "")
        if contract_number and deal.contract_number != contract_number:
            deal.contract_number = contract_number
            update_fields.append("contract_number")

        if str(raw.get("CATEGORY_ID", "0")) == RO_PIPELINE_ID:
            contract_date = parse_date(
                raw.get(RO_CONTRACT_DATE_FIELD)
                or raw.get(STANDARD_CONTRACT_DATE_FIELD)
            )
            if contract_date and deal.contract_date != contract_date:
                deal.contract_date = contract_date
                update_fields.append("contract_date")

        if update_fields:
            deal.save(update_fields=update_fields)


class Migration(migrations.Migration):
    dependencies = [
        ("analytics", "0009_crmdeal_contract_number"),
    ]

    operations = [
        migrations.RunPython(backfill_ro_contract_fields, migrations.RunPython.noop),
    ]
