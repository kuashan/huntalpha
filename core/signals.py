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


@receiver(post_save, sender=AccountMembership, dispatch_uid="core_workspace_prune_after_tier_change")
def prune_downgraded_workspace(sender, instance, using, **kwargs):
    """Admin changes to FREE permanently remove formerly PRO-only chart codes.

    Queryset.update() bypasses signals; GET/PUT workspace independently prune
    against the current persisted tier, including for such legacy updates.
    """
    if instance.tier != AccountMembership.Tier.FREE:
        return
    from .models import AccountWorkspace
    if not AccountWorkspace.objects.using(using).filter(user_id=instance.user_id).exists():
        return
    from .views import COMMON_INDICATORS
    from .workspace import read_workspace
    read_workspace(instance.user, COMMON_INDICATORS)
