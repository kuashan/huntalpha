# Additive only: does not copy or alter account data, formulas or browser preferences.
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
            name="ChartWorkspace",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("main", models.JSONField(default=list)),
                ("sub", models.JSONField(default=list)),
                ("pane_heights", models.JSONField(default=dict)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("user", models.OneToOneField(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="chart_workspace",
                    to=settings.AUTH_USER_MODEL,
                )),
            ],
            options={
                "verbose_name": "图表工作区",
                "verbose_name_plural": "图表工作区",
            },
        ),
    ]
