# Additive pre-launch account security tables. No historical user rows are touched.
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("core", "0011_accountmembership")]

    operations = [
        migrations.CreateModel(
            name="PendingEmailRegistration",
            fields=[
                ("id", models.BigAutoField(primary_key=True, serialize=False)),
                ("email", models.EmailField(max_length=150, unique=True)),
                ("display_name", models.CharField(blank=True, max_length=150)),
                ("password_hash", models.CharField(max_length=128)),
                ("code_hash", models.CharField(max_length=128)),
                ("expires_at", models.DateTimeField()),
                ("sent_at", models.DateTimeField()),
                ("failed_attempts", models.PositiveSmallIntegerField(default=0)),
            ],
        ),
        migrations.CreateModel(
            name="AuthRateLimit",
            fields=[
                ("key", models.CharField(max_length=64, primary_key=True, serialize=False)),
                ("count", models.PositiveIntegerField(default=0)),
                ("window_ends_at", models.DateTimeField()),
            ],
        ),
    ]
