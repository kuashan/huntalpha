# Task 012: state-only table, existing Formula rows are untouched.
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("formula_editor", "0001_initial")]

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
