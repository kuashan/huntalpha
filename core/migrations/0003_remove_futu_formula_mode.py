from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("core", "0002_indicator_language")]

    operations = [
        migrations.RemoveField(model_name="indicator", name="language"),
        migrations.AlterField(
            model_name="indicator",
            name="source",
            field=models.TextField(verbose_name="通达信指标公式源码（仅管理员可见）"),
        ),
    ]
