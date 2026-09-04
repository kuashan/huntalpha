from django.contrib import admin
from .forms import FormulaAdminForm
from .models import Formula


@admin.register(Formula)
class FormulaAdmin(admin.ModelAdmin):
    form = FormulaAdminForm
    list_display = ("code", "name", "placement", "version", "enabled", "updated_at")
    list_filter = ("placement", "enabled")
    search_fields = ("code", "name", "source")
    readonly_fields = ("created_at", "updated_at")
    fieldsets = (
        ("指标信息", {"fields": ("name", "code", "placement", "enabled")} ),
        ("通达信公式", {"fields": ("source",), "description": "源码仅保存在服务器，前端用户只能看到指标名称和绘图结果。"}),
        ("版本记录", {"fields": ("version", "created_at", "updated_at")} ),
    )
