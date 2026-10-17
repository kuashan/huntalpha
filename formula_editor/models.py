from django.db import models


class Formula(models.Model):
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
    updated_at = models.DateTimeField("最后修改", auto_now=True)

    class Meta:
        ordering = ["placement", "name"]
        verbose_name = "通达信公式"
        verbose_name_plural = "通达信公式"

    def __str__(self):
        return f"{self.code} · {self.name}"


class FixedIndicatorState(models.Model):
    """Only persistent on/off state; executable definitions live in trusted code."""

    code = models.CharField("固定公式代码", max_length=32, primary_key=True)
    enabled = models.BooleanField("启用", default=False)

    class Meta:
        verbose_name = "固定公式（服务器已安装）"
        verbose_name_plural = "固定公式（服务器已安装）"

    def __str__(self):
        return self.code
