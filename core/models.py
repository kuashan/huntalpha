from django.conf import settings
from django.db import models


class CalibrationDataset(models.Model):
    """Private imported OHLCV source used to reproduce a desktop chart."""
    id = models.BigAutoField(primary_key=True)
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

    id = models.BigAutoField(primary_key=True)
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


class MarketSymbol(models.Model):
    """HuntAlpha's provider-neutral directory entry for a listed security."""

    class Market(models.TextChoices):
        CN = "cn", "沪深 A 股"
        HK = "hk", "港股"
        US = "us", "美股"

    code = models.CharField("统一证券代码", max_length=32, unique=True)
    name = models.CharField("证券名称", max_length=160)
    market = models.CharField("HuntAlpha 市场", max_length=8, choices=Market.choices)
    exchange = models.CharField("交易所/Provider 市场", max_length=32, blank=True)
    security_type = models.CharField("证券类型", max_length=16)
    active = models.BooleanField("当前有效", default=True)
    provider = models.CharField("数据提供方", max_length=32)
    provider_symbol = models.CharField("Provider 证券代码", max_length=32)
    market_cap = models.DecimalField("总市值", max_digits=24, decimal_places=4, null=True, blank=True)
    market_cap_currency = models.CharField("市值币种", max_length=8, blank=True)
    market_cap_updated_at = models.DateTimeField("市值更新时间", null=True, blank=True)
    catalog_updated_at = models.DateTimeField("目录更新时间", auto_now=True)

    class Meta:
        ordering = ["market", "name", "code"]
        indexes = [
            models.Index(fields=["market", "active"]),
            models.Index(fields=["market", "-market_cap"]),
        ]
        verbose_name = "证券目录"
        verbose_name_plural = "证券目录"

    def __str__(self):
        return f"{self.code} · {self.name}"


class WatchlistEntry(models.Model):
    """A durable account-to-security relationship, without copied quote data."""

    id = models.AutoField(primary_key=True)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="watchlist_entries",
        verbose_name="用户",
    )
    symbol = models.ForeignKey(
        MarketSymbol,
        on_delete=models.PROTECT,
        related_name="watchlist_entries",
        verbose_name="证券",
    )
    created_at = models.DateTimeField("创建时间", auto_now_add=True)

    class Meta:
        ordering = ["created_at", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["user", "symbol"],
                name="core_watch_user_symbol_uniq",
            ),
        ]
        indexes = [
            models.Index(
                fields=["user", "created_at"],
                name="core_watch_user_created_idx",
            ),
        ]
        verbose_name = "账户自选"
        verbose_name_plural = "账户自选"

    def __str__(self):
        return f"{self.user_id} · {self.symbol_id}"
