from datetime import date

from django.core.management.base import BaseCommand

from apps.analytics.services import rebuild_first_zz, rebuild_manager_daily_metrics


class Command(BaseCommand):
    help = "Rebuild first ZZ dates and daily manager metrics from stored CRM data."

    def add_arguments(self, parser):
        parser.add_argument("--start-date", type=date.fromisoformat)
        parser.add_argument("--end-date", type=date.fromisoformat)
        parser.add_argument("--skip-first-zz", action="store_true")

    def handle(self, *args, **options):
        first_zz = None
        if not options["skip_first_zz"]:
            first_zz = rebuild_first_zz()
        rows = rebuild_manager_daily_metrics(options["start_date"], options["end_date"])
        self.stdout.write(self.style.SUCCESS(f"Rebuilt first_zz={first_zz}, daily_metrics={rows}"))

