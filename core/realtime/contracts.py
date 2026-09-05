from dataclasses import dataclass, replace
from datetime import datetime, timezone
from math import isfinite
from zoneinfo import ZoneInfo


MARKET_TIMEZONES = {
    "cn": "Asia/Shanghai",
    "hk": "Asia/Hong_Kong",
    "us": "America/New_York",
    "crypto": "UTC",
}


def market_for_symbol(symbol):
    prefix = str(symbol or "").upper().split(".", 1)[0]
    return {
        "SH": "cn", "SZ": "cn", "HK": "hk", "US": "us", "CC": "crypto",
    }.get(prefix)


def optional_numeric(value):
    """Preserve real zeroes while mapping missing/non-finite values to None."""
    if value is None or value == "":
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if isfinite(number) else None


def provider_time_to_timestamp(value, market=None):
    """Convert provider time keys using the market timezone, never host local time."""
    if isinstance(value, (int, float)):
        return int(value) if isfinite(value) else None
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    parsed = None
    for candidate in (text, text.replace("Z", "+00:00")):
        try:
            parsed = datetime.fromisoformat(candidate)
            break
        except ValueError:
            continue
    if parsed is None:
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
            try:
                parsed = datetime.strptime(text, fmt)
                break
            except ValueError:
                continue
    if parsed is None:
        return None
    if parsed.tzinfo is None:
        tz_name = MARKET_TIMEZONES.get(market or "", "UTC")
        parsed = parsed.replace(tzinfo=ZoneInfo(tz_name))
    return int(parsed.astimezone(timezone.utc).timestamp())


def timestamp_to_market_datetime(timestamp, market):
    tz_name = MARKET_TIMEZONES.get(market or "", "UTC")
    return datetime.fromtimestamp(int(timestamp), tz=timezone.utc).astimezone(ZoneInfo(tz_name))


@dataclass(frozen=True)
class NormalizedBar:
    provider: str
    market: str
    symbol: str
    period: str
    time: int
    open: float | None
    high: float | None
    low: float | None
    close: float | None
    volume: float | None
    amount: float | None = None
    turnover_rate: float | None = None
    is_closed: bool | None = False
    provider_timestamp: int | None = None
    sequence: int | str | None = None
    revision: int = 0
    mode: str = "streaming"
    event_kind: str = "live"

    def to_dict(self):
        return {
            "provider": self.provider,
            "market": self.market,
            "symbol": self.symbol,
            "period": self.period,
            "time": self.time,
            "open": self.open,
            "high": self.high,
            "low": self.low,
            "close": self.close,
            "volume": self.volume,
            "amount": self.amount,
            "turnover_rate": self.turnover_rate,
            "is_closed": self.is_closed,
            "provider_timestamp": self.provider_timestamp,
            "sequence": self.sequence,
            "revision": self.revision,
            "mode": self.mode,
            "event_kind": self.event_kind,
        }


@dataclass(frozen=True)
class MergeResult:
    bar: NormalizedBar | None
    accepted: bool
    relation: str


def _first(*values):
    return next((value for value in values if value is not None), None)


def merge_realtime_bar(existing, incoming):
    """Merge live bars conservatively and reconcile snapshots authoritatively."""
    if existing is None:
        return MergeResult(incoming, True, "initial")
    if incoming.time < existing.time:
        return MergeResult(existing, False, "stale")
    if incoming.time == existing.time:
        if incoming.event_kind in {"reconcile", "authoritative"}:
            return MergeResult(incoming, incoming != existing, "reconciled" if incoming != existing else "duplicate")
        if existing.sequence is not None and incoming.sequence is not None:
            try:
                if incoming.sequence < existing.sequence:
                    return MergeResult(existing, False, "stale")
            except TypeError:
                pass
        for field in ("volume", "amount"):
            current_value = getattr(existing, field)
            incoming_value = getattr(incoming, field)
            if current_value is not None and incoming_value is not None and incoming_value < current_value:
                return MergeResult(existing, False, "suspected_stale")
        high_values = [value for value in (existing.high, incoming.high) if value is not None]
        low_values = [value for value in (existing.low, incoming.low) if value is not None]
        merged = replace(
            existing,
            provider=incoming.provider or existing.provider,
            market=incoming.market or existing.market,
            open=_first(existing.open, incoming.open),
            high=max(high_values) if high_values else None,
            low=min(low_values) if low_values else None,
            close=_first(incoming.close, existing.close),
            volume=max(value for value in (existing.volume, incoming.volume) if value is not None) if any(value is not None for value in (existing.volume, incoming.volume)) else None,
            amount=max(value for value in (existing.amount, incoming.amount) if value is not None) if any(value is not None for value in (existing.amount, incoming.amount)) else None,
            turnover_rate=_first(incoming.turnover_rate, existing.turnover_rate),
            is_closed=bool(existing.is_closed or incoming.is_closed),
            provider_timestamp=_first(incoming.provider_timestamp, existing.provider_timestamp),
            sequence=_first(incoming.sequence, existing.sequence),
            mode=incoming.mode or existing.mode,
            event_kind="live",
        )
        return MergeResult(merged, merged != existing, "updated" if merged != existing else "duplicate")
    closed = replace(existing, is_closed=True)
    return MergeResult(incoming, True, "appended")
