from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.models import User

from .models import (
    BusinessDirection,
    CrmDeal,
    CrmLead,
    CrmPipeline,
    CrmStage,
    CrmUser,
    DashboardUserProfile,
    DealFirstZZ,
    DealStageEvent,
    ManagerDailyMetric,
    SyncCursor,
    SyncRun,
)


class DashboardUserProfileInline(admin.StackedInline):
    model = DashboardUserProfile
    can_delete = False
    extra = 0
    autocomplete_fields = ("crm_user",)


class UserAdmin(BaseUserAdmin):
    inlines = [DashboardUserProfileInline]


admin.site.unregister(User)
admin.site.register(User, UserAdmin)


@admin.register(DashboardUserProfile)
class DashboardUserProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "crm_user")
    search_fields = ("user__username", "user__email", "crm_user__name")
    autocomplete_fields = ("user", "crm_user")


@admin.register(BusinessDirection)
class BusinessDirectionAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "is_active")


@admin.register(CrmUser)
class CrmUserAdmin(admin.ModelAdmin):
    list_display = ("bitrix_id", "name", "email", "is_active")
    search_fields = ("name", "email", "bitrix_id")


@admin.register(CrmPipeline)
class CrmPipelineAdmin(admin.ModelAdmin):
    list_display = ("bitrix_id", "name", "direction", "is_active")
    list_filter = ("direction", "is_active")


@admin.register(CrmStage)
class CrmStageAdmin(admin.ModelAdmin):
    list_display = ("bitrix_id", "name", "pipeline", "sort", "is_zz", "is_zn", "is_success")
    list_filter = ("pipeline", "is_zz", "is_zn", "is_success")
    search_fields = ("bitrix_id", "name")


@admin.register(CrmLead)
class CrmLeadAdmin(admin.ModelAdmin):
    list_display = ("bitrix_id", "title", "created_time", "assigned_by", "direction", "status_id")
    list_filter = ("direction", "status_id")
    search_fields = ("bitrix_id", "title")
    date_hierarchy = "created_time"


@admin.register(CrmDeal)
class CrmDealAdmin(admin.ModelAdmin):
    list_display = ("bitrix_id", "title", "pipeline", "stage", "created_time", "assigned_by", "direction", "contract_number", "contract_date", "contract_amount")
    list_filter = ("pipeline", "stage", "direction")
    search_fields = ("bitrix_id", "title", "contract_number")
    date_hierarchy = "created_time"


@admin.register(DealStageEvent)
class DealStageEventAdmin(admin.ModelAdmin):
    list_display = ("deal", "stage_id_raw", "changed_at", "assigned_by", "source_event_id")
    list_filter = ("stage_id_raw",)
    date_hierarchy = "changed_at"


@admin.register(DealFirstZZ)
class DealFirstZZAdmin(admin.ModelAdmin):
    list_display = ("deal", "first_zz_at", "stage", "assigned_by", "source")
    date_hierarchy = "first_zz_at"


@admin.register(ManagerDailyMetric)
class ManagerDailyMetricAdmin(admin.ModelAdmin):
    list_display = ("metric_date", "manager", "direction", "leads", "target_leads", "zz", "contracts", "contract_amount")
    list_filter = ("direction", "manager")
    date_hierarchy = "metric_date"


@admin.register(SyncRun)
class SyncRunAdmin(admin.ModelAdmin):
    list_display = ("source", "status", "started_at", "finished_at")
    list_filter = ("source", "status")
    readonly_fields = ("stats", "error")


@admin.register(SyncCursor)
class SyncCursorAdmin(admin.ModelAdmin):
    list_display = ("name", "value", "updated_at")
