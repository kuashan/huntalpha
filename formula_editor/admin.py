from django.contrib import admin, messages
from django.core.exceptions import PermissionDenied
from django.http import Http404, HttpResponseNotAllowed
from django.shortcuts import redirect
from django.template.response import TemplateResponse
from django.urls import path, reverse

from core.python_indicators import get_python_indicator
from .fixed_indicators import installed_fixed_indicators, is_fixed_indicator_enabled
from .forms import FormulaAdminForm
from .models import FixedIndicatorState, Formula


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


@admin.register(FixedIndicatorState)
class FixedIndicatorStateAdmin(admin.ModelAdmin):
    """Virtual catalog: no upload, source editor, arbitrary model row or runner."""

    change_list_template = "admin/formula_editor/fixedindicatorstate/change_list.html"

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def change_view(self, request, object_id, form_url="", extra_context=None):
        raise Http404

    def add_view(self, request, form_url="", extra_context=None):
        raise Http404

    def get_urls(self):
        return [
            path(
                "toggle/<str:code>/", self.admin_site.admin_view(self.toggle),
                name="formula_editor_fixedindicatorstate_toggle",
            ),
            *super().get_urls(),
        ]

    def changelist_view(self, request, extra_context=None):
        if not self.has_view_or_change_permission(request):
            raise PermissionDenied
        rows = [
            {
                "code": definition.code,
                "name": definition.name,
                "version": definition.version,
                "placement": "主图" if definition.placement == "main" else "副图",
                "enabled": enabled,
                "toggle_url": reverse(
                    "admin:formula_editor_fixedindicatorstate_toggle",
                    args=[definition.code],
                ),
            }
            for definition, enabled in installed_fixed_indicators()
        ]
        context = {
            **self.admin_site.each_context(request),
            "title": self.model._meta.verbose_name_plural,
            "opts": self.model._meta,
            "fixed_indicators": rows,
            "can_change": self.has_change_permission(request),
            **(extra_context or {}),
        }
        return TemplateResponse(request, self.change_list_template, context)

    def toggle(self, request, code):
        if request.method != "POST":
            return HttpResponseNotAllowed(["POST"])
        if not self.has_change_permission(request):
            raise PermissionDenied
        definition = get_python_indicator(code)
        if definition is None or definition.code != code:
            raise Http404
        enabled = not is_fixed_indicator_enabled(definition)
        FixedIndicatorState.objects.update_or_create(
            code=definition.code, defaults={"enabled": enabled},
        )
        messages.success(request, f"{definition.name}已{'启用' if enabled else '停用'}")
        return redirect("admin:formula_editor_fixedindicatorstate_changelist")
