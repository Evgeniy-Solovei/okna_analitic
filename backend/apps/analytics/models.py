from django.conf import settings
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
        RO = "ro", "Русские окна"
        B2B = "b2b", "B2B"

    code = models.CharField(max_length=32, choices=Code.choices, unique=True, verbose_name="Код")
    name = models.CharField(max_length=128, verbose_name="Название")
    is_active = models.BooleanField(default=True, verbose_name="Активно")

    class Meta:
        db_table = "business_directions"
        ordering = ["name"]
        verbose_name = "Направление бизнеса"
        verbose_name_plural = "Направления бизнеса"

    def __str__(self):
        return self.name


class CrmUser(TimestampedModel):
    bitrix_id = models.PositiveBigIntegerField(unique=True, verbose_name="ID в Bitrix")
    name = models.CharField(max_length=255, verbose_name="Имя")
    email = models.EmailField(blank=True, verbose_name="Email")
    is_active = models.BooleanField(default=True, verbose_name="Активен")
    raw = models.JSONField(default=dict, blank=True, verbose_name="Сырые данные")

    class Meta:
        db_table = "crm_users"
        ordering = ["name"]
        verbose_name = "Менеджер Bitrix"
        verbose_name_plural = "Менеджеры Bitrix"

    def __str__(self):
        return self.name


class CrmPipeline(TimestampedModel):
    bitrix_id = models.CharField(max_length=64, unique=True, verbose_name="ID в Bitrix")
    name = models.CharField(max_length=255, verbose_name="Название")
    direction = models.ForeignKey(BusinessDirection, null=True, blank=True, on_delete=models.SET_NULL, verbose_name="Направление")
    is_active = models.BooleanField(default=True, verbose_name="Активна")
    raw = models.JSONField(default=dict, blank=True, verbose_name="Сырые данные")

    class Meta:
        db_table = "crm_pipelines"
        ordering = ["name"]
        verbose_name = "Воронка"
        verbose_name_plural = "Воронки"

    def __str__(self):
        return self.name


class CrmStage(TimestampedModel):
    bitrix_id = models.CharField(max_length=128, unique=True, verbose_name="ID в Bitrix")
    pipeline = models.ForeignKey(CrmPipeline, null=True, blank=True, on_delete=models.SET_NULL, verbose_name="Воронка")
    name = models.CharField(max_length=255, verbose_name="Название")
    sort = models.IntegerField(default=0, verbose_name="Сортировка")
    is_zz = models.BooleanField(default=False, verbose_name="Это ЗЗ")
    is_zn = models.BooleanField(default=False, verbose_name="Это ЗН")
    is_success = models.BooleanField(default=False, verbose_name="Успешная")
    raw = models.JSONField(default=dict, blank=True, verbose_name="Сырые данные")

    class Meta:
        db_table = "crm_stages"
        ordering = ["pipeline_id", "sort", "name"]
        verbose_name = "Стадия сделки"
        verbose_name_plural = "Стадии сделок"
        indexes = [
            models.Index(fields=["pipeline", "is_zz"]),
            models.Index(fields=["pipeline", "is_zn"]),
        ]

    def __str__(self):
        return self.name


class CrmLead(TimestampedModel):
    bitrix_id = models.PositiveBigIntegerField(unique=True, verbose_name="ID в Bitrix")
    title = models.CharField(max_length=500, blank=True, verbose_name="Название")
    status_id = models.CharField(max_length=128, blank=True, verbose_name="Статус")
    created_time = models.DateTimeField(verbose_name="Дата создания")
    assigned_by = models.ForeignKey(CrmUser, null=True, blank=True, on_delete=models.SET_NULL, verbose_name="Ответственный")
    direction = models.ForeignKey(BusinessDirection, null=True, blank=True, on_delete=models.SET_NULL, verbose_name="Направление")
    source_id = models.CharField(max_length=128, blank=True, verbose_name="Источник")
    raw = models.JSONField(default=dict, blank=True, verbose_name="Сырые данные")

    class Meta:
        db_table = "crm_leads"
        verbose_name = "Лид"
        verbose_name_plural = "Лиды"
        indexes = [
            models.Index(fields=["created_time"]),
            models.Index(fields=["assigned_by", "created_time"]),
            models.Index(fields=["direction", "created_time"]),
        ]

    def __str__(self):
        return f"{self.bitrix_id}: {self.title}"


class CrmDeal(TimestampedModel):
    bitrix_id = models.PositiveBigIntegerField(unique=True, verbose_name="ID в Bitrix")
    title = models.CharField(max_length=500, blank=True, verbose_name="Название")
    pipeline = models.ForeignKey(CrmPipeline, null=True, blank=True, on_delete=models.SET_NULL, verbose_name="Воронка")
    stage = models.ForeignKey(CrmStage, null=True, blank=True, on_delete=models.SET_NULL, verbose_name="Стадия")
    lead = models.ForeignKey(CrmLead, null=True, blank=True, on_delete=models.SET_NULL, verbose_name="Лид")
    assigned_by = models.ForeignKey(CrmUser, null=True, blank=True, on_delete=models.SET_NULL, verbose_name="Ответственный")
    direction = models.ForeignKey(BusinessDirection, null=True, blank=True, on_delete=models.SET_NULL, verbose_name="Направление")
    created_time = models.DateTimeField(verbose_name="Дата создания")
    moved_time = models.DateTimeField(null=True, blank=True, verbose_name="Дата перемещения")
    contract_number = models.CharField(max_length=255, blank=True, db_index=True, verbose_name="Номер договора")
    contract_date = models.DateField(null=True, blank=True, verbose_name="Дата договора")
    contract_amount = models.DecimalField(max_digits=14, decimal_places=2, default=0, verbose_name="Сумма договора")
    raw = models.JSONField(default=dict, blank=True, verbose_name="Сырые данные")

    class Meta:
        db_table = "crm_deals"
        verbose_name = "Сделка"
        verbose_name_plural = "Сделки"
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
    deal = models.ForeignKey(CrmDeal, on_delete=models.CASCADE, related_name="stage_events", verbose_name="Сделка")
    stage = models.ForeignKey(CrmStage, null=True, blank=True, on_delete=models.SET_NULL, verbose_name="Стадия")
    stage_id_raw = models.CharField(max_length=128, verbose_name="Исходный ID стадии")
    changed_at = models.DateTimeField(verbose_name="Дата изменения")
    assigned_by = models.ForeignKey(CrmUser, null=True, blank=True, on_delete=models.SET_NULL, verbose_name="Ответственный")
    source_event_id = models.CharField(max_length=128, blank=True, verbose_name="ID события")
    raw = models.JSONField(default=dict, blank=True, verbose_name="Сырые данные")

    class Meta:
        db_table = "deal_stage_events"
        verbose_name = "Событие смены стадии"
        verbose_name_plural = "События смены стадий"
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
    deal = models.OneToOneField(CrmDeal, on_delete=models.CASCADE, related_name="first_zz", verbose_name="Сделка")
    first_zz_at = models.DateTimeField(verbose_name="Первое попадание в ЗЗ")
    stage = models.ForeignKey(CrmStage, null=True, blank=True, on_delete=models.SET_NULL, verbose_name="Стадия")
    assigned_by = models.ForeignKey(CrmUser, null=True, blank=True, on_delete=models.SET_NULL, verbose_name="Ответственный")
    source = models.CharField(max_length=32, default="stage_history", verbose_name="Источник")

    class Meta:
        db_table = "deal_first_zz"
        verbose_name = "Первый ЗЗ"
        verbose_name_plural = "Первые ЗЗ"
        indexes = [
            models.Index(fields=["first_zz_at"]),
            models.Index(fields=["assigned_by", "first_zz_at"]),
        ]


class ManagerDailyMetric(TimestampedModel):
    metric_date = models.DateField(verbose_name="Дата")
    manager = models.ForeignKey(CrmUser, on_delete=models.CASCADE, verbose_name="Менеджер")
    direction = models.ForeignKey(BusinessDirection, on_delete=models.CASCADE, verbose_name="Направление")
    leads = models.PositiveIntegerField(default=0, verbose_name="Лиды")
    target_leads = models.PositiveIntegerField(default=0, verbose_name="Целевые лиды")
    zz = models.PositiveIntegerField(default=0, verbose_name="ЗЗ")
    contracts = models.PositiveIntegerField(default=0, verbose_name="Договоры")
    contract_amount = models.DecimalField(max_digits=16, decimal_places=2, default=0, verbose_name="Сумма договоров")

    class Meta:
        db_table = "manager_daily_metrics"
        verbose_name = "Дневная метрика менеджера"
        verbose_name_plural = "Дневные метрики менеджеров"
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

    source = models.CharField(max_length=64, default="bitrix24", verbose_name="Источник")
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.STARTED, verbose_name="Статус")
    started_at = models.DateTimeField(default=timezone.now, verbose_name="Начало")
    finished_at = models.DateTimeField(null=True, blank=True, verbose_name="Окончание")
    stats = models.JSONField(default=dict, blank=True, verbose_name="Статистика")
    error = models.TextField(blank=True, verbose_name="Ошибка")

    class Meta:
        db_table = "sync_runs"
        verbose_name = "Запуск синхронизации"
        verbose_name_plural = "Запуски синхронизации"
        indexes = [
            models.Index(fields=["source", "started_at"]),
            models.Index(fields=["status", "started_at"]),
        ]


class SyncCursor(TimestampedModel):
    name = models.CharField(max_length=128, unique=True, verbose_name="Имя")
    value = models.CharField(max_length=255, blank=True, verbose_name="Значение")
    payload = models.JSONField(default=dict, blank=True, verbose_name="Данные")

    class Meta:
        db_table = "sync_cursors"
        verbose_name = "Курсор синхронизации"
        verbose_name_plural = "Курсоры синхронизации"


class DashboardUserProfile(models.Model):
    """Связь Django-пользователя с менеджером из Bitrix для ролевого доступа."""

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="dashboard_profile",
        verbose_name="Пользователь Django",
    )
    crm_user = models.ForeignKey(
        CrmUser,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        verbose_name="Менеджер Bitrix",
    )
    allowed_directions = models.ManyToManyField(
        BusinessDirection,
        blank=True,
        verbose_name="Разрешенные направления",
    )

    class Meta:
        db_table = "dashboard_user_profiles"
        verbose_name = "Профиль дашборда"
        verbose_name_plural = "Профили дашборда"

    def __str__(self):
        return f"{self.user.username} → {self.crm_user or '—'}"

