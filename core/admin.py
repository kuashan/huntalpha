from django.contrib import admin
from .models import CalibrationDataset


@admin.register(CalibrationDataset)
class CalibrationDatasetAdmin(admin.ModelAdmin):
    list_display = ("symbol", "name", "period", "adjustment", "float_shares", "imported_at")
    search_fields = ("symbol", "name")
    readonly_fields = ("imported_at",)
    fields = ("symbol", "name", "period", "adjustment", "float_shares", "bars", "imported_at")
