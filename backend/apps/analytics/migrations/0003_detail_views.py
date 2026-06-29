from django.db import migrations


DETAIL_VIEWS_SQL = """
CREATE OR REPLACE VIEW bi_lead_details AS
SELECT
    cl.created_time::date AS event_date,
    cl.bitrix_id AS lead_id,
    cl.title,
    cu.name AS manager,
    bd.name AS direction,
    cl.status_id,
    cl.source_id
FROM crm_leads cl
JOIN crm_users cu ON cu.id = cl.assigned_by_id
LEFT JOIN LATERAL (
    SELECT cd.direction_id
    FROM crm_deals cd
    WHERE cd.lead_id = cl.id AND cd.direction_id IS NOT NULL
    ORDER BY cd.created_time, cd.id
    LIMIT 1
) inferred_deal ON TRUE
JOIN business_directions bd ON bd.id = COALESCE(cl.direction_id, inferred_deal.direction_id);

CREATE OR REPLACE VIEW bi_deal_details AS
SELECT
    cd.created_time::date AS event_date,
    cd.bitrix_id AS deal_id,
    cd.title,
    cu.name AS manager,
    bd.name AS direction,
    cp.name AS pipeline,
    cs.name AS stage,
    cd.contract_date,
    cd.contract_amount
FROM crm_deals cd
JOIN crm_users cu ON cu.id = cd.assigned_by_id
JOIN business_directions bd ON bd.id = cd.direction_id
LEFT JOIN crm_pipelines cp ON cp.id = cd.pipeline_id
LEFT JOIN crm_stages cs ON cs.id = cd.stage_id;

CREATE OR REPLACE VIEW bi_zz_details AS
SELECT
    dfz.first_zz_at::date AS event_date,
    cd.bitrix_id AS deal_id,
    cd.title,
    cu.name AS manager,
    bd.name AS direction,
    cs.name AS zz_stage,
    dfz.first_zz_at
FROM deal_first_zz dfz
JOIN crm_deals cd ON cd.id = dfz.deal_id
JOIN crm_users cu ON cu.id = COALESCE(dfz.assigned_by_id, cd.assigned_by_id)
JOIN business_directions bd ON bd.id = cd.direction_id
LEFT JOIN crm_stages cs ON cs.id = dfz.stage_id;

CREATE OR REPLACE VIEW bi_contract_details AS
SELECT
    cd.contract_date AS event_date,
    cd.bitrix_id AS deal_id,
    cd.title,
    cu.name AS manager,
    bd.name AS direction,
    cp.name AS pipeline,
    cs.name AS stage,
    cd.contract_amount
FROM crm_deals cd
JOIN crm_users cu ON cu.id = cd.assigned_by_id
JOIN business_directions bd ON bd.id = cd.direction_id
LEFT JOIN crm_pipelines cp ON cp.id = cd.pipeline_id
LEFT JOIN crm_stages cs ON cs.id = cd.stage_id
WHERE cd.contract_date IS NOT NULL;
"""


DROP_DETAIL_VIEWS_SQL = """
DROP VIEW IF EXISTS bi_contract_details;
DROP VIEW IF EXISTS bi_zz_details;
DROP VIEW IF EXISTS bi_deal_details;
DROP VIEW IF EXISTS bi_lead_details;
"""


class Migration(migrations.Migration):
    dependencies = [
        ("analytics", "0002_seed_directions_and_views"),
    ]

    operations = [
        migrations.RunSQL(DETAIL_VIEWS_SQL, reverse_sql=DROP_DETAIL_VIEWS_SQL),
    ]
