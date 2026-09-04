from django.db import migrations, models


def copy_existing_formulas(apps, schema_editor):
    Indicator = apps.get_model("core", "Indicator")
    Formula = apps.get_model("formula_editor", "Formula")
    for item in Indicator.objects.all():
        Formula.objects.update_or_create(code=item.code, defaults={"name": item.name, "placement": item.placement, "source": item.source, "version": item.version, "enabled": item.enabled})


class Migration(migrations.Migration):
    initial = True
    dependencies = [("core", "0003_remove_futu_formula_mode")]
    operations = [
        migrations.CreateModel(name="Formula", fields=[
            ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
            ("name", models.CharField(max_length=80, verbose_name="指标名称")),
            ("code", models.CharField(max_length=32, unique=True, verbose_name="指标代码")),
            ("placement", models.CharField(choices=[("main", "主图"), ("sub", "副图")], default="sub", max_length=8, verbose_name="显示位置")),
            ("source", models.TextField(verbose_name="通达信指标公式源码（仅管理员可见）")),
            ("version", models.PositiveIntegerField(default=1, verbose_name="版本")),
            ("enabled", models.BooleanField(default=True, verbose_name="启用")),
            ("created_at", models.DateTimeField(auto_now_add=True, verbose_name="创建时间")),
            ("updated_at", models.DateTimeField(auto_now=True, verbose_name="最后修改")),
        ], options={"verbose_name": "通达信公式", "verbose_name_plural": "通达信公式", "ordering": ["placement", "name"]}),
        migrations.RunPython(copy_existing_formulas, migrations.RunPython.noop),
    ]
