"""V1.1.4: add nullable expiration without rewriting existing memberships."""
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("core", "0013_chartworkspace")]

    operations = [
        migrations.AddField(
            model_name="accountmembership",
            name="expires_at",
            field=models.DateTimeField("PRO 到期时间", blank=True, null=True),
        ),
    ]
