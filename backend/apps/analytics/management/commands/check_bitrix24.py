from django.conf import settings
from django.core.management.base import BaseCommand

from apps.analytics.bitrix import BitrixClient


def stage_entity_id(category_id: str) -> str:
    return "DEAL_STAGE" if str(category_id) == "0" else f"DEAL_STAGE_{category_id}"


class Command(BaseCommand):
    help = "Check Bitrix24 webhook access without storing CRM data."

    def handle(self, *args, **options):
        client = BitrixClient.from_settings()

        profile = client.call("profile")
        lead_page = client.call_raw("crm.lead.list", {"select": ["ID"], "order": {"ID": "DESC"}})
        deal_page = client.call_raw(
            "crm.deal.list",
            {
                "select": ["ID", "CATEGORY_ID", "STAGE_ID"],
                "order": {"ID": "DESC"},
            },
        )
        deal_fields = client.call("crm.deal.fields") or {}
        lead_fields = client.call("crm.lead.fields") or {}
        categories_result = client.call("crm.category.list", {"entityTypeId": 2}) or {}
        categories = categories_result.get("categories", categories_result if isinstance(categories_result, list) else [])

        self.stdout.write("Bitrix24 webhook check")
        self.stdout.write(f"Portal: {settings.BITRIX24['BASE_URL']}")
        self.stdout.write(f"User ID: {profile.get('ID')}, admin: {profile.get('ADMIN')}")
        self.stdout.write(f"Leads available: {lead_page.get('total', len(lead_page.get('result', [])))}")
        self.stdout.write(f"Deals available: {deal_page.get('total', len(deal_page.get('result', [])))}")
        self.stdout.write(f"Lead fields: {len(lead_fields)}")
        self.stdout.write(f"Deal fields: {len(deal_fields)}")

        self.stdout.write("\nDeal categories:")
        for category in categories:
            self.stdout.write(f"- {category.get('id')}: {category.get('name')}")

        self.stdout.write("\nConfigured sales funnels:")
        configured = [
            ("PANORAMA", settings.BITRIX24["PANORAMA_PIPELINE_ID"], settings.BITRIX24["PANORAMA_ZZ_STAGE_ID"]),
            ("RO", settings.BITRIX24["RO_PIPELINE_ID"], settings.BITRIX24["RO_ZZ_STAGE_ID"]),
        ]
        for label, category_id, zz_stage_id in configured:
            statuses = client.call("crm.status.list", {"filter": {"ENTITY_ID": stage_entity_id(category_id)}}) or []
            zz_stage = next((stage for stage in statuses if stage.get("STATUS_ID") == zz_stage_id), None)
            self.stdout.write(
                f"- {label}: category={category_id}, stages={len(statuses)}, "
                f"zz_stage={zz_stage_id}, zz_name={zz_stage.get('NAME') if zz_stage else 'NOT FOUND'}"
            )

        deals = deal_page.get("result", [])
        if deals:
            deal_id = deals[0]["ID"]
            history = client.call(
                "crm.stagehistory.list",
                {"entityTypeId": 2, "filter": {"OWNER_ID": deal_id}, "order": {"ID": "ASC"}},
            )
            history_items = history.get("items", history if isinstance(history, list) else [])
            self.stdout.write(f"\nStage history for latest deal {deal_id}: {len(history_items)} events")
            for item in history_items[:5]:
                self.stdout.write(f"- {item.get('CREATED_TIME')}: {item.get('STAGE_ID')}")

