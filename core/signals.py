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
