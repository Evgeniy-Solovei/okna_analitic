from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("analytics", "0008_dashboard_user_profile"),
    ]

    operations = [
        migrations.AddField(
            model_name="crmdeal",
            name="contract_number",
            field=models.CharField(
                blank=True,
                db_index=True,
                max_length=255,
                verbose_name="Номер договора",
            ),
        ),
    ]
