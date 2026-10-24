"""Read-only per-symbol technical score using the pinned original StockTrendAnalyzer.

The six score dimensions, decision gates, indicators and thresholds are computed
ONLY by core.vendor.daily_stock_analysis.stock_analyzer. This module normalizes
SiftAlpha's existing provider-neutral DAILY candles, not a new strategy.
"""
from __future__ import annotations

from datetime import datetime, time as clock_time, timezone
import math
from zoneinfo import ZoneInfo

import pandas as pd

from .marketdata.profiles import profile_for
from .marketdata.service import get_market_data_service, market_id_for_symbol
from .vendor.daily_stock_analysis.stock_analyzer import StockTrendAnalyzer


MIN_DAILY_BARS = 60
MAX_DAILY_BARS = 120


class TechnicalMomentumUnavailable(Exception):
    def __init__(self, status: str):
        self.status = status
        super().__init__(status)


def _finite(value, *, positive=False):
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (ValueError, TypeError, OverflowError):
        return None
    if not math.isfinite(number) or (positive and number <= 0):
        return None
    return number


def _timestamp(value, zone):
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        number = _finite(value)
        if number is None:
            return None
        try:
            return datetime.fromtimestamp(number, tz=timezone.utc)
        except (ValueError, OverflowError, OSError):
            return None
    if isinstance(value, str):
        candidate = value.strip()
        if not candidate:
            return None
        if candidate.isdigit():
            if len(candidate) in (8, 14):
                try:
                    fmt = "%Y%m%d%H%M%S" if len(candidate) == 14 else "%Y%m%d"
                    return datetime.strptime(candidate, fmt).replace(tzinfo=zone).astimezone(timezone.utc)
                except ValueError:
                    return None
            return _timestamp(int(candidate), zone)
        try:
            stamp = datetime.fromisoformat(candidate.replace("Z", "+00:00"))
        except ValueError:
            return None
        return (stamp.replace(tzinfo=zone) if stamp.tzinfo is None else stamp).astimezone(timezone.utc)
    return None


def _bar(row, zone, provider):
    if not isinstance(row, dict):
        return None
    if row.get("provider") not in (None, provider):
        return None
    if row.get("period") not in (None, "日线", "1d"):
        return None
    stamp = _timestamp(row.get("time", row.get("timestamp", row.get("date"))), zone)
    if stamp is None:
        return None
    prices = {key: _finite(row.get(key), positive=True) for key in ("open", "high", "low", "close")}
    volume = _finite(row.get("volume"))
    if any(value is None for value in prices.values()) or volume is None or volume < 0:
        return None
    if prices["low"] > min(prices["open"], prices["close"]) or prices["high"] < max(prices["open"], prices["close"]):
        return None
    if prices["high"] < prices["low"]:
        return None
    return {"date": stamp.astimezone(zone).date().isoformat(), **prices, "volume": volume}


def _is_market_open(profile, now):
    if profile.continuous:
        return True
    local = now.astimezone(ZoneInfo(profile.timezone))
    if local.weekday() >= 5:
        return False
    return any(
        clock_time.fromisoformat(start) <= local.time().replace(tzinfo=None) <= clock_time.fromisoformat(end)
        for start, end in profile.sessions
    )


def _merge_verified_quote(rows, quote, *, code, provider, profile, now):
    """Use only a fresh quote from the SAME historical provider and local day."""
    if not isinstance(quote, dict) or quote.get("source") != provider:
        return False
    if str(quote.get("code", "")).upper() != code.upper():
        return False
    zone = ZoneInfo(profile.timezone)
    updated = _timestamp(quote.get("updated_at"), zone)
    if updated is None or updated > now.replace(tzinfo=timezone.utc) or (now - updated).total_seconds() > 3600:
        return False
    today = now.astimezone(zone).date().isoformat()
    if updated.astimezone(zone).date().isoformat() != today:
        return False
    price = _finite(quote.get("price"), positive=True)
    if price is None:
        return False

    latest = rows[-1] if rows else None
    if latest and latest["date"] == today:
        # Avoid overwriting the original provider's complete OHLCV when its
        # quote does not have matching daily fields.
        latest["close"] = price
        hi = _finite(quote.get("high"), positive=True)
        lo = _finite(quote.get("low"), positive=True)
        latest["high"] = max(latest["high"], price, hi or price)
        latest["low"] = min(latest["low"], price, lo or price)
        vol = _finite(quote.get("volume"))
        if vol is not None and vol >= 0:
            latest["volume"] = vol
        return True

    # Only construct a new daily candle when the source actually exposes all
    # same-session OHLCV; otherwise keep last completed daily score.
    fields = {key: _finite(quote.get(key), positive=True) for key in ("open", "high", "low")}
    vol = _finite(quote.get("volume"))
    if any(value is None for value in fields.values()) or vol is None or vol < 0:
        return False
    rows.append({
        "date": today,
        "open": fields["open"],
        "high": max(fields["high"], price, fields["open"]),
        "low": min(fields["low"], price, fields["open"]),
        "close": price,
        "volume": vol,
    })
    return True


def analyze_technical_momentum(code: str, *, service=None, now=None):
    """Build a daily window and run the unchanged upstream scoring engine."""
    service = service or get_market_data_service()
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    now = now.astimezone(timezone.utc)
    profile = profile_for(market_id_for_symbol(code))
    zone = ZoneInfo(profile.timezone)
    try:
        fetch = service.window_for_symbol(code, "日线", limit=MAX_DAILY_BARS)
    except Exception as exc:
        raise TechnicalMomentumUnavailable(getattr(exc, "status", "unavailable")) from exc
    if fetch.meta.get("stale") or not fetch.completed:
        raise TechnicalMomentumUnavailable("unavailable")

    rows = []
    for raw in fetch.completed:
        row = _bar(raw, zone, fetch.provider_id)
        if row is not None:
            rows.append(row)
    rows.sort(key=lambda row: row["date"])
    unique = {row["date"]: row for row in rows}
    rows = [unique[key] for key in sorted(unique)]

    if fetch.forming is not None:
        forming = _bar(fetch.forming, zone, fetch.provider_id)
        if forming is not None:
            unique[forming["date"]] = forming
            rows = [unique[key] for key in sorted(unique)]

    if len(rows) < MIN_DAILY_BARS:
        raise TechnicalMomentumUnavailable("insufficient_history")

    today = now.astimezone(zone).date().isoformat()
    intraday = rows[-1]["date"] == today and _is_market_open(profile, now)
    if _is_market_open(profile, now) and not profile.continuous:
        # Reuse the existing quote source; never merge different providers or
        # stale/off-session quotes. Crypto candles are daily UTC already and
        # Coinbase rolling-24h OHLCV must not overwrite calendar-day OHLCV.
        try:
            quote = service.quote_for_symbol(code)
            if _merge_verified_quote(rows, quote, code=code, provider=fetch.provider_id, profile=profile, now=now):
                intraday = True
        except Exception:
            pass

    rows = rows[-MAX_DAILY_BARS:]
    last = rows[-1]
    # Reject missing/latest invalid volume rather than invent zero volume.
    frame = pd.DataFrame(rows, columns=["date", "open", "high", "low", "close", "volume"])
    result = StockTrendAnalyzer().analyze(frame, code)
    if not (0 <= result.signal_score <= 100):
        raise TechnicalMomentumUnavailable("invalid_result")

    return {
        "status": "ready",
        "code": code.upper(),
        "period": "1d",
        "source": "ZhuLinsen/daily_stock_analysis",
        "provider": fetch.provider_id,
        "score": result.signal_score,
        "signal": result.buy_signal.value,
        "score_band": {
            "min": (result.signal_score // 20) * 20,
            "max": min(100, (result.signal_score // 20) * 20 + 19),
        },
        "date": last["date"],
        "intraday": bool(intraday),
        "dimensions": [
            {"key": "trend", "max_score": 30, "detail": result.trend_status.value},
            {"key": "bias", "max_score": 20, "detail": f"{result.bias_ma5:+.2f}%"},
            {"key": "volume", "max_score": 15, "detail": result.volume_status.value},
            {"key": "support", "max_score": 10, "detail": ("MA5 " if result.support_ma5 else "") + ("MA10" if result.support_ma10 else "") or "—"},
            {"key": "macd", "max_score": 15, "detail": result.macd_status.value},
            {"key": "rsi", "max_score": 10, "detail": f"RSI12 {result.rsi_12:.1f}"},
        ],
        "history_bars": len(rows),
    }
