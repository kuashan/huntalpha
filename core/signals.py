"""Create a durable FREE membership for every newly saved account."""
from django.conf import settings
from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import AccountMembership


@receiver(post_save, sender=settings.AUTH_USER_MODEL, dispatch_uid="core_accountmembership_create")
def create_account_membership(sender, instance, created, using, **kwargs):
    if created:
        AccountMembership.objects.using(using).get_or_create(
            user_id=instance.pk, defaults={"tier": AccountMembership.Tier.FREE}
        )


@receiver(post_save, sender=AccountMembership, dispatch_uid="core_chartworkspace_prune_downgrade")
def prune_chart_workspace_on_membership_change(sender, instance, created, **kwargs):
    # Admin tier changes must discard revoked indicators rather than freeze them.
    # Membership bulk-update paths are covered by workspace GET normalization.
    if not created and instance.tier == AccountMembership.Tier.FREE:
        from .chart_workspace import prune_workspace_for_user
        prune_workspace_for_user(instance.user_id)
