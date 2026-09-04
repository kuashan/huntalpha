from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("core", "0004_calibrationdataset")]

    operations = [
        migrations.AddField(
            model_name="calibrationdataset",
            name="float_shares",
            field=models.FloatField(blank=True, help_text="筹码分布计算使用；缺失时 COST/WINNER 只作中性近似", null=True, verbose_name="流通股本（股）"),
        ),
    ]
