"""V1.1.5: independent source settings; no existing market or account rows changed."""
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("core", "0014_accountmembership_expires_at")]

    operations = [
        migrations.CreateModel(
            name="MarketDataSourceSetting",
            fields=[
                ("market", models.CharField(choices=[("us", "美股"), ("cn", "沪深 A 股"), ("hk", "港股"), ("crypto", "加密货币")], max_length=8, primary_key=True, serialize=False, verbose_name="市场")),
                ("provider", models.CharField(default="auto", max_length=32, verbose_name="行情来源")),
                ("updated_at", models.DateTimeField(auto_now=True, verbose_name="修改时间")),
            ],
            options={"verbose_name": "行情来源", "verbose_name_plural": "行情来源"},
        ),
    ]
