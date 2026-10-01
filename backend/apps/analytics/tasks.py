from celery import shared_task

from .services import run_bitrix24_sync


@shared_task
def sync_bitrix24_full():
    return run_bitrix24_sync(mode="full", source="bitrix24_celery_full")


@shared_task(soft_time_limit=12 * 60, time_limit=14 * 60)
def sync_bitrix24_incremental(force_reconcile: bool = False):
    return run_bitrix24_sync(
        mode="incremental",
        source="bitrix24_celery_incremental",
        force_reconcile=force_reconcile,
    )
