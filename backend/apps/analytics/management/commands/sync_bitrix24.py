from django.core.management.base import BaseCommand

from apps.analytics.services import run_bitrix24_sync


class Command(BaseCommand):
    help = "Synchronize Bitrix24 CRM data and rebuild manager metrics."

    def add_arguments(self, parser):
        parser.add_argument("--full", action="store_true", help="Full sync: load all Bitrix24 data.")
        parser.add_argument("--incremental", action="store_true", help="Incremental sync: load records modified since last cursor.")
        parser.add_argument("--skip-history", action="store_true", help="Do not request deal stage history.")

    def handle(self, *args, **options):
        if options["full"] and options["incremental"]:
            raise ValueError("Use either --full or --incremental, not both.")

        mode = "incremental" if options["incremental"] else "full"
        stats = run_bitrix24_sync(mode=mode, skip_history=options["skip_history"], source="bitrix24")
        self.stdout.write(self.style.SUCCESS(f"Sync complete: {stats}"))
