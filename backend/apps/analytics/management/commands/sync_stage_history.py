from django.core.management.base import BaseCommand

from apps.analytics.bitrix import BitrixClient
from apps.analytics.models import CrmDeal, DealFirstZZ, DealStageEvent, ManagerDailyMetric
from apps.analytics.services import rebuild_first_zz, rebuild_manager_daily_metrics, sync_deal_stage_history


class Command(BaseCommand):
    help = "Synchronize Bitrix24 deal stage history and rebuild ZZ metrics."

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, help="Limit newest deals for local checks.")

    def handle(self, *args, **options):
        client = BitrixClient.from_settings()
        deal_ids = None
        if options["limit"]:
            deal_ids = list(CrmDeal.objects.order_by("-bitrix_id").values_list("bitrix_id", flat=True)[: options["limit"]])

        events = sync_deal_stage_history(client, deal_ids=deal_ids)
        first_zz = rebuild_first_zz()
        daily_metrics = rebuild_manager_daily_metrics()

        self.stdout.write(
            self.style.SUCCESS(
                "Stage history sync complete: "
                f"events_written={events}, "
                f"events_total={DealStageEvent.objects.count()}, "
                f"first_zz={first_zz}, "
                f"first_zz_total={DealFirstZZ.objects.count()}, "
                f"daily_metrics={daily_metrics}, "
                f"metrics_total={ManagerDailyMetric.objects.count()}"
            )
        )
