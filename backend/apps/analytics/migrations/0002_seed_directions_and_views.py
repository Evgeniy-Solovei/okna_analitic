from django.db import migrations


CREATE_VIEWS = """
CREATE OR REPLACE VIEW bi_manager_daily_metrics AS
SELECT
    mdm.metric_date,
    cu.name AS manager,
    bd.name AS direction,
    mdm.leads,
    mdm.target_leads,
    mdm.zz,
    CASE
        WHEN mdm.target_leads = 0 THEN 0
        ELSE ROUND((mdm.zz::numeric / mdm.target_leads::numeric) * 100, 2)
    END AS conversion_percent,
    mdm.contracts,
    mdm.contract_amount,
    CASE
        WHEN mdm.contracts = 0 THEN 0
        ELSE ROUND(mdm.contract_amount / mdm.contracts, 2)
    END AS avg_check
FROM manager_daily_metrics mdm
JOIN crm_users cu ON cu.id = mdm.manager_id
JOIN business_directions bd ON bd.id = mdm.direction_id;

CREATE OR REPLACE VIEW bi_manager_period_totals AS
SELECT
    cu.name AS manager,
    bd.name AS direction,
    SUM(mdm.leads) AS leads,
    SUM(mdm.target_leads) AS target_leads,
    SUM(mdm.zz) AS zz,
    CASE
        WHEN SUM(mdm.target_leads) = 0 THEN 0
        ELSE ROUND((SUM(mdm.zz)::numeric / SUM(mdm.target_leads)::numeric) * 100, 2)
    END AS conversion_percent,
    SUM(mdm.contracts) AS contracts,
    SUM(mdm.contract_amount) AS contract_amount,
    CASE
        WHEN SUM(mdm.contracts) = 0 THEN 0
        ELSE ROUND(SUM(mdm.contract_amount) / SUM(mdm.contracts), 2)
    END AS avg_check
FROM manager_daily_metrics mdm
JOIN crm_users cu ON cu.id = mdm.manager_id
JOIN business_directions bd ON bd.id = mdm.direction_id
GROUP BY cu.name, bd.name;
"""


DROP_VIEWS = """
DROP VIEW IF EXISTS bi_manager_period_totals;
DROP VIEW IF EXISTS bi_manager_daily_metrics;
"""


def seed_directions(apps, _schema_editor):
    BusinessDirection = apps.get_model("analytics", "BusinessDirection")
    BusinessDirection.objects.update_or_create(code="panorama", defaults={"name": "Панорама", "is_active": True})
    BusinessDirection.objects.update_or_create(code="ro", defaults={"name": "РО", "is_active": True})


class Migration(migrations.Migration):
    dependencies = [
        ("analytics", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(seed_directions, migrations.RunPython.noop),
        migrations.RunSQL(CREATE_VIEWS, DROP_VIEWS),
    ]

