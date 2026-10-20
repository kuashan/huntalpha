"""Period calculation for superuser grants; reusable by a future payment service.

No public grant or payment endpoint is exposed.
"""
from calendar import monthrange
from datetime import timedelta

from django.utils import timezone

from .models import AccountMembership

DURATION_CHOICES = (
    ("7d", "7 天"), ("1m", "1 个月"), ("3m", "3 个月"),
    ("6m", "半年"), ("1y", "1 年"),
)
_MONTHS = {"1m": 1, "3m": 3, "6m": 6, "1y": 12}


def period_end(start, duration):
    """Add calendar months/years, clamping month-end and retaining time-of-day."""
    if duration == "7d":
        return start + timedelta(days=7)
    if duration not in _MONTHS:
        raise ValueError("不支持的会员时长")
    year, zero_month = divmod(start.year * 12 + start.month - 1 + _MONTHS[duration], 12)
    month = zero_month + 1
    return start.replace(year=year, month=month, day=min(start.day, monthrange(year, month)[1]))


def grant_pro_period(membership, duration, *, now=None):
    """Grant/extend without saving. Active finite PRO extends from its expiry."""
    instant = now if now is not None else timezone.now()
    start = (membership.expires_at
             if membership.tier == AccountMembership.Tier.PRO
             and membership.expires_at is not None
             and membership.expires_at > instant else instant)
    expiry = period_end(start, duration)
    membership.tier = AccountMembership.Tier.PRO
    membership.expires_at = expiry
    return expiry
