from celery import shared_task

from .services import run_bitrix24_sync


@shared_task
def sync_bitrix24_full():
    return run_bitrix24_sync(mode="full", source="bitrix24_celery_full")


@shared_task
def sync_bitrix24_incremental():
    return run_bitrix24_sync(mode="incremental", source="bitrix24_celery_incremental")
