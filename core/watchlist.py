from django.conf import settings
from django.utils import timezone
from .models import AccountMembership


def resolve_account_tier(user):
    """Use the database entitlement only; missing legacy rows default to FREE."""
    if not getattr(user, "is_authenticated", False):
        return None
    # A fresh query avoids retaining a stale PRO tier if an admin downgrades
    # the account while the user's session is still active.
    membership = AccountMembership.objects.filter(user_id=user.pk).values("tier", "expires_at").first()
    if not membership or membership["tier"] != AccountMembership.Tier.PRO:
        return AccountMembership.Tier.FREE
    expiry = membership["expires_at"]
    return AccountMembership.Tier.PRO if expiry is None or expiry > timezone.now() else AccountMembership.Tier.FREE


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


def active_watchlist_entry_ids(user):
    """Ordered, account-global active entries; frozen rows stay in the database.

    The slice is made *before* any market or search filter, so changing markets
    cannot unfreeze extra records or consume another market's quota.
    """
    from .models import WatchlistEntry

    if not getattr(user, "is_authenticated", False):
        return WatchlistEntry.objects.none().values("pk")
    return (
        WatchlistEntry.objects.filter(user_id=user.pk)
        .order_by("created_at", "id")
        .values("pk")[:resolve_watchlist_limit(user)]
    )
