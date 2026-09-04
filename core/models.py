from django.db import models


class CalibrationDataset(models.Model):
    """Private imported OHLCV source used to reproduce a desktop chart."""
    symbol = models.CharField("证券代码", max_length=32, unique=True)
    name = models.CharField("证券名称", max_length=80)
    period = models.CharField("周期", max_length=16, default="日线")
    adjustment = models.CharField("复权方式", max_length=32, blank=True)
    float_shares = models.FloatField("流通股本（股）", null=True, blank=True, help_text="筹码分布计算使用；缺失时 COST/WINNER 只作中性近似")
    bars = models.JSONField("K线数据")
    imported_at = models.DateTimeField("导入时间", auto_now=True)

    class Meta:
        verbose_name = "通达信校准数据"
        verbose_name_plural = "通达信校准数据"


class Indicator(models.Model):
    class Placement(models.TextChoices):
        MAIN = "main", "主图"
        SUB = "sub", "副图"

    name = models.CharField("指标名称", max_length=80)
    code = models.CharField("指标代码", max_length=32, unique=True)
    placement = models.CharField("显示位置", max_length=8, choices=Placement.choices, default=Placement.SUB)
    source = models.TextField("通达信指标公式源码（仅管理员可见）")
    version = models.PositiveIntegerField("版本", default=1)
    enabled = models.BooleanField("启用", default=True)
    created_at = models.DateTimeField("创建时间", auto_now_add=True)
    updated_at = models.DateTimeField("更新时间", auto_now=True)

    class Meta:
        ordering = ["placement", "name"]
        verbose_name = "自定义指标"
        verbose_name_plural = "自定义指标"

    def __str__(self):
        return f"{self.code} · {self.name}"
