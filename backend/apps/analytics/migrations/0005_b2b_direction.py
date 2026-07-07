from django.db import migrations


def seed_b2b_direction(apps, _schema_editor):
    BusinessDirection = apps.get_model("analytics", "BusinessDirection")
    BusinessDirection.objects.update_or_create(code="b2b", defaults={"name": "B2B", "is_active": True})


class Migration(migrations.Migration):
    dependencies = [
        ("analytics", "0004_rename_auto_indexes"),
    ]

    operations = [
        migrations.RunPython(seed_b2b_direction, migrations.RunPython.noop),
    ]
