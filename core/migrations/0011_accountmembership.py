# Generated for Task 011: persist the real FREE/PRO tier without touching user data.
from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


def backfill_existing_users(apps, schema_editor):
    app_label, model_name = settings.AUTH_USER_MODEL.split(".")
    User = apps.get_model(app_label, model_name)
    Membership = apps.get_model("core", "AccountMembership")
    database = schema_editor.connection.alias
    pending = []
    for user_id in User.objects.using(database).order_by("pk").values_list("pk", flat=True).iterator(chunk_size=500):
        pending.append(Membership(user_id=user_id, tier="free"))
        if len(pending) == 500:
            Membership.objects.using(database).bulk_create(pending, ignore_conflicts=True, batch_size=500)
            pending.clear()
    if pending:
        Membership.objects.using(database).bulk_create(pending, ignore_conflicts=True, batch_size=500)


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0010_alter_accountprofile_default_market_and_more"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="AccountMembership",
            fields=[
                ("id", models.AutoField(primary_key=True, serialize=False)),
                ("tier", models.CharField(choices=[("free", "FREE"), ("pro", "PRO")], default="free", max_length=4, verbose_name="会员等级")),
                ("user", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name="account_membership", to=settings.AUTH_USER_MODEL, verbose_name="用户")),
            ],
            options={"verbose_name": "会员等级", "verbose_name_plural": "会员等级"},
        ),
        migrations.RunPython(backfill_existing_users, migrations.RunPython.noop),
    ]
