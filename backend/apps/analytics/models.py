from django.db import models
from django.utils import timezone


class TimestampedModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class BusinessDirection(TimestampedModel):
    class Code(models.TextChoices):
        PANORAMA = "panorama", "Панорама"
        RO = "ro", "РО"

    code = models.CharField(max_length=32, choices=Code.choices, unique=True)
    name = models.CharField(max_length=128)
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "business_directions"
        ordering = ["name"]

    def __str__(self):
        return self.name


class CrmUser(TimestampedModel):
    bitrix_id = models.PositiveBigIntegerField(unique=True)
    name = models.CharField(max_length=255)
    email = models.EmailField(blank=True)
    is_active = models.BooleanField(default=True)
    raw = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = "crm_users"
        ordering = ["name"]

    def __str__(self):
        return self.name


class CrmPipeline(TimestampedModel):
    bitrix_id = models.CharField(max_length=64, unique=True)
    name = models.CharField(max_length=255)
    direction = models.ForeignKey(BusinessDirection, null=True, blank=True, on_delete=models.SET_NULL)
    is_active = models.BooleanField(default=True)
    raw = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = "crm_pipelines"
        ordering = ["name"]

    def __str__(self):
        return self.name


class CrmStage(TimestampedModel):
    bitrix_id = models.CharField(max_length=128, unique=True)
    pipeline = models.ForeignKey(CrmPipeline, null=True, blank=True, on_delete=models.SET_NULL)
    name = models.CharField(max_length=255)
    sort = models.IntegerField(default=0)
    is_zz = models.BooleanField(default=False)
    is_zn = models.BooleanField(default=False)
    is_success = models.BooleanField(default=False)
    raw = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = "crm_stages"
        ordering = ["pipeline_id", "sort", "name"]
        indexes = [
            models.Index(fields=["pipeline", "is_zz"]),
            models.Index(fields=["pipeline", "is_zn"]),
        ]

    def __str__(self):
        return self.name


class CrmLead(TimestampedModel):
    bitrix_id = models.PositiveBigIntegerField(unique=True)
    title = models.CharField(max_length=500, blank=True)
    status_id = models.CharField(max_length=128, blank=True)
    created_time = models.DateTimeField()
    assigned_by = models.ForeignKey(CrmUser, null=True, blank=True, on_delete=models.SET_NULL)
    direction = models.ForeignKey(BusinessDirection, null=True, blank=True, on_delete=models.SET_NULL)
    source_id = models.CharField(max_length=128, blank=True)
    raw = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = "crm_leads"
        indexes = [
            models.Index(fields=["created_time"]),
            models.Index(fields=["assigned_by", "created_time"]),
            models.Index(fields=["direction", "created_time"]),
        ]

    def __str__(self):
        return f"{self.bitrix_id}: {self.title}"


class CrmDeal(TimestampedModel):
    bitrix_id = models.PositiveBigIntegerField(unique=True)
    title = models.CharField(max_length=500, blank=True)
    pipeline = models.ForeignKey(CrmPipeline, null=True, blank=True, on_delete=models.SET_NULL)
    stage = models.ForeignKey(CrmStage, null=True, blank=True, on_delete=models.SET_NULL)
    lead = models.ForeignKey(CrmLead, null=True, blank=True, on_delete=models.SET_NULL)
    assigned_by = models.ForeignKey(CrmUser, null=True, blank=True, on_delete=models.SET_NULL)
    direction = models.ForeignKey(BusinessDirection, null=True, blank=True, on_delete=models.SET_NULL)
    created_time = models.DateTimeField()
    moved_time = models.DateTimeField(null=True, blank=True)
    contract_date = models.DateField(null=True, blank=True)
    contract_amount = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    raw = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = "crm_deals"
        indexes = [
            models.Index(fields=["created_time"]),
            models.Index(fields=["contract_date"]),
            models.Index(fields=["assigned_by", "created_time"]),
            models.Index(fields=["assigned_by", "contract_date"]),
            models.Index(fields=["direction", "created_time"]),
            models.Index(fields=["pipeline", "stage"]),
        ]

    def __str__(self):
        return f"{self.bitrix_id}: {self.title}"


class DealStageEvent(TimestampedModel):
    deal = models.ForeignKey(CrmDeal, on_delete=models.CASCADE, related_name="stage_events")
    stage = models.ForeignKey(CrmStage, null=True, blank=True, on_delete=models.SET_NULL)
    stage_id_raw = models.CharField(max_length=128)
    changed_at = models.DateTimeField()
    assigned_by = models.ForeignKey(CrmUser, null=True, blank=True, on_delete=models.SET_NULL)
    source_event_id = models.CharField(max_length=128, blank=True)
    raw = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = "deal_stage_events"
        constraints = [
            models.UniqueConstraint(
                fields=["deal", "stage_id_raw", "changed_at", "source_event_id"],
                name="uniq_deal_stage_event_source",
            )
        ]
        indexes = [
            models.Index(fields=["deal", "changed_at"]),
            models.Index(fields=["stage_id_raw", "changed_at"]),
            models.Index(fields=["assigned_by", "changed_at"]),
        ]


class DealFirstZZ(TimestampedModel):
    deal = models.OneToOneField(CrmDeal, on_delete=models.CASCADE, related_name="first_zz")
    first_zz_at = models.DateTimeField()
    stage = models.ForeignKey(CrmStage, null=True, blank=True, on_delete=models.SET_NULL)
    assigned_by = models.ForeignKey(CrmUser, null=True, blank=True, on_delete=models.SET_NULL)
    source = models.CharField(max_length=32, default="stage_history")

    class Meta:
        db_table = "deal_first_zz"
        indexes = [
            models.Index(fields=["first_zz_at"]),
            models.Index(fields=["assigned_by", "first_zz_at"]),
        ]


class ManagerDailyMetric(TimestampedModel):
    metric_date = models.DateField()
    manager = models.ForeignKey(CrmUser, on_delete=models.CASCADE)
    direction = models.ForeignKey(BusinessDirection, on_delete=models.CASCADE)
    leads = models.PositiveIntegerField(default=0)
    target_leads = models.PositiveIntegerField(default=0)
    zz = models.PositiveIntegerField(default=0)
    contracts = models.PositiveIntegerField(default=0)
    contract_amount = models.DecimalField(max_digits=16, decimal_places=2, default=0)

    class Meta:
        db_table = "manager_daily_metrics"
        constraints = [
            models.UniqueConstraint(
                fields=["metric_date", "manager", "direction"],
                name="uniq_manager_daily_metric",
            )
        ]
        indexes = [
            models.Index(fields=["metric_date"]),
            models.Index(fields=["manager", "metric_date"]),
            models.Index(fields=["direction", "metric_date"]),
        ]

    @property
    def conversion(self):
        if not self.target_leads:
            return 0
        return self.zz / self.target_leads


class SyncRun(TimestampedModel):
    class Status(models.TextChoices):
        STARTED = "started", "Started"
        SUCCESS = "success", "Success"
        FAILED = "failed", "Failed"

    source = models.CharField(max_length=64, default="bitrix24")
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.STARTED)
    started_at = models.DateTimeField(default=timezone.now)
    finished_at = models.DateTimeField(null=True, blank=True)
    stats = models.JSONField(default=dict, blank=True)
    error = models.TextField(blank=True)

    class Meta:
        db_table = "sync_runs"
        indexes = [
            models.Index(fields=["source", "started_at"]),
            models.Index(fields=["status", "started_at"]),
        ]


class SyncCursor(TimestampedModel):
    name = models.CharField(max_length=128, unique=True)
    value = models.CharField(max_length=255, blank=True)
    payload = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = "sync_cursors"

