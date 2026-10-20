from django import forms
from django.contrib import admin
from django.utils import timezone
from django.contrib.auth import get_user_model
from django.contrib.auth.admin import UserAdmin

from .models import AccountMembership, AccountProfile, CalibrationDataset, MarketSymbol, WatchlistEntry
from .membership import DURATION_CHOICES, grant_pro_period


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
