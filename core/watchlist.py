from django.conf import settings
from .models import AccountMembership


def resolve_account_tier(user):
    """Use the database entitlement only; missing legacy rows default to FREE."""
    if not getattr(user, "is_authenticated", False):
        return None
    # A fresh query avoids retaining a stale PRO tier if an admin downgrades
    # the account while the user's session is still active.
    tier = AccountMembership.objects.filter(user_id=user.pk).values_list("tier", flat=True).first()
    return tier if tier in {AccountMembership.Tier.FREE, AccountMembership.Tier.PRO} else AccountMembership.Tier.FREE


def resolve_watchlist_limit(user):
    """Resolve the configured quota for the account's real tier."""
    tier = resolve_account_tier(user)
    if tier == "pro":
        return settings.HUNTALPHA_WATCHLIST_PRO_LIMIT
    if tier == "free":
        return settings.HUNTALPHA_WATCHLIST_FREE_LIMIT
    return None


def account_tier_payload(user):
    tier = resolve_account_tier(user)
    return {
        "tier": tier,
        "tier_label": tier.upper() if tier else None,
        "watchlist_limit": resolve_watchlist_limit(user),
    }


def watchlist_limit_for_user(user):
    """Backward-compatible watchlist quota entry point."""
    return resolve_watchlist_limit(user)
