from django.conf import settings


def watchlist_limit_for_user(user):
    """Resolve the durable quota in one place until entitlements are real."""
    # The repository has no persisted subscription/entitlement model yet. Do
    # not infer Pro from staff, superuser, username, or any other proxy.
    return settings.HUNTALPHA_WATCHLIST_FREE_LIMIT
