from django.contrib import admin
from .models import CalibrationDataset, MarketSymbol, WatchlistEntry


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
