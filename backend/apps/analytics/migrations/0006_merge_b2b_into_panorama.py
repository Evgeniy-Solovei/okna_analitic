import os

from django.db import migrations


def merge_b2b_into_panorama(apps, _schema_editor):
    BusinessDirection = apps.get_model("analytics", "BusinessDirection")
    CrmPipeline = apps.get_model("analytics", "CrmPipeline")
    CrmDeal = apps.get_model("analytics", "CrmDeal")

    panorama = BusinessDirection.objects.filter(code="panorama").first()
    b2b = BusinessDirection.objects.filter(code="b2b").first()
    if not panorama:
        return

    if b2b:
        CrmDeal.objects.filter(direction=b2b).update(direction=panorama)
        b2b.is_active = False
        b2b.save(update_fields=["is_active"])

    b2b_pipeline_id = os.getenv("B2B_PIPELINE_ID", "1")
    CrmPipeline.objects.filter(bitrix_id=str(b2b_pipeline_id)).update(direction=panorama)


class Migration(migrations.Migration):
    dependencies = [
        ("analytics", "0005_b2b_direction"),
    ]

    operations = [
        migrations.RunPython(merge_b2b_into_panorama, migrations.RunPython.noop),
    ]
