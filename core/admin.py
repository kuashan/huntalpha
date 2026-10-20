from django import forms
from django.contrib import admin, messages
from django.db import transaction
from django.http import HttpResponseRedirect
from django.template.response import TemplateResponse
from django.utils import timezone
from django.contrib.auth import get_user_model
from django.contrib.auth.admin import UserAdmin

from .models import AccountMembership, AccountProfile, CalibrationDataset, MarketDataSourceSetting, MarketSymbol, WatchlistEntry
from .membership import DURATION_CHOICES, grant_pro_period
from .marketdata.selection import PROVIDER_LABELS, PROVIDERS_BY_MARKET


@admin.register(AccountProfile)
class AccountProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "price_color_mode", "default_market", "default_period", "updated_at")
    search_fields = ("user__username", "user__email", "user__first_name")
    readonly_fields = ("updated_at",)


@admin.register(CalibrationDataset)
class CalibrationDatasetAdmin(admin.ModelAdmin):
    list_display = ("symbol", "name", "period", "adjustment", "float_shares", "imported_at")
    search_fields = ("symbol", "name")
    readonly_fields = ("imported_at",)
    fields = ("symbol", "name", "period", "adjustment", "float_shares", "bars", "imported_at")


@admin.register(MarketSymbol)
class MarketSymbolAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "market", "exchange", "security_type", "active", "market_cap", "market_cap_currency", "catalog_updated_at")
    list_filter = ("market", "active", "security_type", "provider")
    search_fields = ("code", "name", "provider_symbol")
    readonly_fields = ("catalog_updated_at", "market_cap_updated_at")


@admin.register(WatchlistEntry)
class WatchlistEntryAdmin(admin.ModelAdmin):
    list_display = ("user", "symbol", "created_at")
    list_filter = ("symbol__market",)
    search_fields = ("user__username", "user__email", "symbol__code", "symbol__name")
    readonly_fields = ("created_at",)



class MarketDataSourceForm(forms.Form):
    """All four independent global market choices on a single admin page."""

    us = forms.ChoiceField(label="美股", choices=[(p, PROVIDER_LABELS[p]) for p in PROVIDERS_BY_MARKET["us"]])
    cn = forms.ChoiceField(label="沪深 A 股", choices=[(p, PROVIDER_LABELS[p]) for p in PROVIDERS_BY_MARKET["cn"]])
    hk = forms.ChoiceField(label="港股", choices=[(p, PROVIDER_LABELS[p]) for p in PROVIDERS_BY_MARKET["hk"]])
    crypto = forms.ChoiceField(label="加密货币", choices=[(p, PROVIDER_LABELS[p]) for p in PROVIDERS_BY_MARKET["crypto"]])


@admin.register(MarketDataSourceSetting)
class MarketDataSourceSettingAdmin(admin.ModelAdmin):
    change_list_template = "admin/core/marketdatasourcesetting/changelist.html"

    def _superuser(self, request):
        return bool(request.user.is_active and request.user.is_superuser)

    def has_module_permission(self, request):
        return self._superuser(request)

    def has_view_permission(self, request, obj=None):
        return self._superuser(request)

    def has_change_permission(self, request, obj=None):
        return self._superuser(request)

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def changelist_view(self, request, extra_context=None):
        if not self._superuser(request):
            from django.core.exceptions import PermissionDenied
            raise PermissionDenied
        initial = {key: "auto" for key in PROVIDERS_BY_MARKET}
        initial.update(dict(MarketDataSourceSetting.objects.values_list("market", "provider")))
        if request.method == "POST":
            form = MarketDataSourceForm(request.POST)
            if form.is_valid():
                with transaction.atomic():
                    for market, provider in form.cleaned_data.items():
                        MarketDataSourceSetting.objects.update_or_create(
                            market=market, defaults={"provider": provider}
                        )
                self.message_user(request, "四个市场的行情来源已保存，新请求立即使用最新选择。", messages.SUCCESS)
                return HttpResponseRedirect(request.path)
        else:
            form = MarketDataSourceForm(initial=initial)
        context = {
            **self.admin_site.each_context(request),
            "title": "行情来源",
            "opts": self.model._meta,
            "form": form,
            **(extra_context or {}),
        }
        return TemplateResponse(request, self.change_list_template, context)



class AccountMembershipForm(forms.ModelForm):
    grant_duration = forms.ChoiceField(
        label="增加会员时长", required=False,
        choices=(("", "不增加"), *DURATION_CHOICES),
        help_text="已生效且尚未到期的 PRO 从原到期时刻顺延，否则从保存时刻起算。",
    )

    class Meta:
        model = AccountMembership
        fields = ("tier", "expires_at")

    def save(self, commit=True):
        membership = super().save(commit=False)
        if self.cleaned_data.get("grant_duration"):
            grant_pro_period(membership, self.cleaned_data["grant_duration"])
        if commit:
            membership.save()
            self.save_m2m()
        return membership


class AccountMembershipInline(admin.StackedInline):
    """Only real superusers may create or edit an account's subscription tier."""

    model = AccountMembership
    form = AccountMembershipForm
    fields = ("tier", "expires_at", "grant_duration")
    extra = 1
    max_num = 1
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return bool(request.user.is_superuser)

    def has_change_permission(self, request, obj=None):
        return bool(request.user.is_superuser)

    def has_delete_permission(self, request, obj=None):
        return False


class MembershipUserAdmin(UserAdmin):
    list_display = (*UserAdmin.list_display, "account_tier_display")

    @admin.display(description="会员等级")
    def account_tier_display(self, obj):
        try:
            record = obj.account_membership
            if record.tier == "pro" and record.expires_at and record.expires_at <= timezone.now():
                return "FREE (PRO 已到期)"
            return record.tier.upper()
        except AccountMembership.DoesNotExist:
            return "FREE"

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("account_membership")

    def get_inlines(self, request, obj=None):
        # Even a forged POST by non-superuser staff cannot inject a membership
        # formset: the editable inline does not exist for that request.
        return [AccountMembershipInline] if obj is not None and request.user.is_superuser else []


UserModel = get_user_model()
if admin.site.is_registered(UserModel):
    admin.site.unregister(UserModel)
admin.site.register(UserModel, MembershipUserAdmin)
