from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("core", "0001_initial")]

    operations = [
        migrations.AddField(
            model_name="indicator",
            name="language",
            field=models.CharField(choices=[("tdx", "通达信公式"), ("futu", "富途公式（兼容）")], default="tdx", max_length=8, verbose_name="公式语言"),
        ),
        migrations.AlterField(
            model_name="indicator",
            name="source",
            field=models.TextField(verbose_name="指标公式源码（仅管理员可见）"),
        ),
    ]
