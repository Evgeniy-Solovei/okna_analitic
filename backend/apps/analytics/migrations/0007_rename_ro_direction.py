from django.db import migrations


def rename_ro_direction(apps, _schema_editor):
    BusinessDirection = apps.get_model("analytics", "BusinessDirection")
    BusinessDirection.objects.filter(code="ro").update(name="Русские окна")


class Migration(migrations.Migration):
    dependencies = [
        ("analytics", "0006_merge_b2b_into_panorama"),
    ]

    operations = [
        migrations.RunPython(rename_ro_direction, migrations.RunPython.noop),
    ]
