import django.db.models.deletion
import django.utils.timezone
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("analytics", "0013_seed_direction_groups"),
    ]

    operations = [
        migrations.AddField(
            model_name="crmdeal",
            name="measure_scheduled_at",
            field=models.DateTimeField(blank=True, null=True, verbose_name="Дата и время замера"),
        ),
        migrations.AddField(
            model_name="crmdeal",
            name="measurer",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="measured_deals",
                to="analytics.crmuser",
                verbose_name="Замерщик",
            ),
        ),
        migrations.AddIndex(
            model_name="crmdeal",
            index=models.Index(fields=["measurer", "measure_scheduled_at"], name="crm_deals_measure_sched_idx"),
        ),
        migrations.AddIndex(
            model_name="crmdeal",
            index=models.Index(fields=["measurer", "contract_date"], name="crm_deals_measure_contr_idx"),
        ),
        migrations.CreateModel(
            name="MeasurerDailyMetric",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now, editable=False)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("metric_date", models.DateField(verbose_name="Дата")),
                ("measures", models.PositiveIntegerField(default=0, verbose_name="Замеры")),
                ("contracts", models.PositiveIntegerField(default=0, verbose_name="Договоры")),
                (
                    "contract_amount",
                    models.DecimalField(decimal_places=2, default=0, max_digits=16, verbose_name="Сумма договоров"),
                ),
                (
                    "direction",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        to="analytics.businessdirection",
                        verbose_name="Направление",
                    ),
                ),
                (
                    "measurer",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="measurer_metrics",
                        to="analytics.crmuser",
                        verbose_name="Замерщик",
                    ),
                ),
            ],
            options={
                "verbose_name": "Дневная метрика замерщика",
                "verbose_name_plural": "Дневные метрики замерщиков",
                "db_table": "measurer_daily_metrics",
            },
        ),
        migrations.AddIndex(
            model_name="measurerdailymetric",
            index=models.Index(fields=["metric_date"], name="measurer_da_metric__idx"),
        ),
        migrations.AddIndex(
            model_name="measurerdailymetric",
            index=models.Index(fields=["measurer", "metric_date"], name="measurer_da_measure_idx"),
        ),
        migrations.AddIndex(
            model_name="measurerdailymetric",
            index=models.Index(fields=["direction", "metric_date"], name="measurer_da_directi_idx"),
        ),
        migrations.AddConstraint(
            model_name="measurerdailymetric",
            constraint=models.UniqueConstraint(
                fields=("metric_date", "measurer", "direction"),
                name="uniq_measurer_daily_metric",
            ),
        ),
    ]
