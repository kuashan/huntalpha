"""Canonical exchange-local calendar anchors for stock and crypto K-lines.

Only calendar periods are re-keyed. Intraday exchange timestamps and all OHLCV
values remain source-owned. Every provider flows through MarketDataFetch.
"""
from __future__ import annotations

from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from .profiles import CN_A_SHARE, CRYPTO_24_7, HK_EQUITY, US_EQUITY

CALENDAR_PERIODS = frozenset({"日线", "周线", "月线"})
_MARKET_TIMEZONES = {
    profile.market_id: profile.timezone
    for profile in (CN_A_SHARE, HK_EQUITY, US_EQUITY, CRYPTO_24_7)
}
_MARKET_TIMEZONES.update({
    "cn": CN_A_SHARE.timezone,
    "hk": HK_EQUITY.timezone,
    "us": US_EQUITY.timezone,
    "crypto": CRYPTO_24_7.timezone,
})


def canonical_calendar_time(timestamp: int, market_id: str, period: str) -> int:
    """Map a bar to its exchange-local day/week/month anchor, not server UTC day."""
    if period not in CALENDAR_PERIODS:
        return int(timestamp)
    zone_name = _MARKET_TIMEZONES.get(str(market_id or ""), "UTC")
    zone = ZoneInfo(zone_name)
    date = datetime.fromtimestamp(int(timestamp), tz=zone).date()
    if period == "周线":
        date -= timedelta(days=date.weekday())
    elif period == "月线":
        date = date.replace(day=1)
    return int(datetime.combine(date, time.min, tzinfo=zone).timestamp())


def canonical_calendar_bar(bar, market_id: str, period: str):
    if period not in CALENDAR_PERIODS or not isinstance(bar, dict) or bar.get("time") is None:
        return bar
    return {**bar, "time": canonical_calendar_time(bar["time"], market_id, period)}


def canonical_calendar_rows(rows: list, market_id: str, period: str) -> list:
    if period not in CALENDAR_PERIODS:
        return list(rows)
    # One authoritative source for the entire window: never synthesize/merge OHLCV.
    # If that source returned repeated calendar buckets, keep its latest record.
    keyed = {}
    unkeyed = []
    for original in rows:
        bar = canonical_calendar_bar(original, market_id, period)
        if isinstance(bar, dict) and bar.get("time") is not None:
            keyed[bar["time"]] = bar
        else:
            unkeyed.append(bar)
    return [keyed[key] for key in sorted(keyed)] + unkeyed
