# Task 005.2: additive, account-scoped chart settings; no data migration.
from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0012_auth_verification"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="AccountWorkspace",
            fields=[
                ("user", models.OneToOneField(
                    on_delete=django.db.models.deletion.CASCADE,
                    primary_key=True, related_name="chart_workspace",
                    serialize=False, to=settings.AUTH_USER_MODEL,
                )),
                ("main_indicators", models.JSONField(default=list)),
                ("sub_indicators", models.JSONField(default=list)),
                ("sub_pane_heights", models.JSONField(default=dict)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "verbose_name": "账户图表工作区",
                "verbose_name_plural": "账户图表工作区",
            },
        ),
    ]
