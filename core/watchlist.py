from django.conf import settings


def resolve_account_tier(user):
    """Return the real account tier, without inferring Pro from user flags."""
    # The repository has no persisted subscription/entitlement model yet. Do
    # not infer Pro from staff, superuser, username, or any other proxy.
    return "free" if getattr(user, "is_authenticated", False) else None


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
