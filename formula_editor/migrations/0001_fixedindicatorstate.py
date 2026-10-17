# Task 012: new state-only table. Never modify existing Formula rows or sources.
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name="FixedIndicatorState",
            fields=[
                ("code", models.CharField(max_length=32, primary_key=True, serialize=False, verbose_name="固定公式代码")),
                ("enabled", models.BooleanField(default=False, verbose_name="启用")),
            ],
            options={
                "verbose_name": "固定公式（服务器已安装）",
                "verbose_name_plural": "固定公式（服务器已安装）",
            },
        ),
    ]
