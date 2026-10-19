from __future__ import annotations

"""无密钥 Yahoo Finance Chart Provider。

核心窗口解析、交易时段判断、形成中 K 线分离和 4 小时聚合遵循
SiftAlpha/SLTD 已验证的 Yahoo 实现；这里仅把它适配到 HuntAlpha 的
MarketProfile、MarketDataFetch 契约和内部证券代码格式。
"""

import json
import math
import time
from datetime import datetime, time as datetime_time, timedelta, timezone
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from ..profiles import CN_A_SHARE, HK_EQUITY, US_EQUITY, MarketProfile
from .base import MarketDataProviderError, unavailable_status


YAHOO_PROVIDER = "yahoo-finance"
MIN_COMPLETED_BARS = 120

_PERIODS = {
    "1分": {"interval": "1m", "lookback_days": 7, "seconds": 60},
    "5分": {"interval": "5m", "lookback_days": 60, "seconds": 300},
    "15分": {"interval": "15m", "lookback_days": 60, "seconds": 900},
    "30分": {"interval": "30m", "lookback_days": 60, "seconds": 1800},
    "60分": {"interval": "60m", "lookback_days": 730, "seconds": 3600},
    "2小时": {"interval": "60m", "lookback_days": 730, "seconds": 7200, "aggregate_from": "60分", "factor": 2},
    "4小时": {"interval": "60m", "lookback_days": 730, "seconds": 14400, "aggregate_from": "60分", "factor": 4},
    "日线": {"interval": "1d", "lookback_days": None, "seconds": 86400},
    "周线": {"interval": "1wk", "lookback_days": None, "seconds": 7 * 86400},
    "月线": {"interval": "1mo", "lookback_days": None, "seconds": 31 * 86400},
}


def yahoo_symbol_for(symbol: str) -> str:
    normalized = str(symbol or "").strip().upper()
    prefix, separator, body = normalized.partition(".")
    if not separator:
        return normalized
    if prefix not in {"SH", "SSE", "SZ", "SZSE", "HK", "US", "CC"} and body in {"SH", "SSE", "SZ", "SZSE", "HK", "US", "CC"}:
        prefix, body = body, prefix
    if prefix in {"SH", "SSE"}:
        return f"{body}.SS"
    if prefix in {"SZ", "SZSE"}:
        return f"{body}.SZ"
    if prefix == "HK":
        # HuntAlpha accepts both 700 and 00700; Yahoo uses the four-digit
        # Hong Kong ticker (0700.HK), so normalize by stripping an optional
        # vendor zero prefix before padding.
        return f"{body.lstrip('0').zfill(4)}.HK"
    if prefix == "US":
        return body
    if prefix == "CC":
        return body
    return normalized


def _number(value):
    try:
        return None if value is None else float(value)
    except (TypeError, ValueError):
        return None


def _recent_previous_close(price, closes):
    """Resolve the latest session close from a chart response.

    ``chartPreviousClose`` is tied to the beginning of Yahoo's requested
    window.  It is not a safe previous close for a long-range quote request.
    When the latest chart close is the current market price, the preceding
    close is the prior session's close; otherwise the latest chart close is
    the best available prior close.
    """
    valid = [value for value in (_number(item) for item in (closes or [])) if value is not None]
    if len(valid) >= 2 and price is not None:
        tolerance = max(1e-9, abs(price) * 1e-6)
        if abs(valid[-1] - price) <= tolerance:
            return valid[-2]
    return valid[-1] if valid else None


def _timestamp(value, market: MarketProfile) -> int | None:
    if isinstance(value, (int, float)):
        return int(value)
    text = str(value or "").strip().replace("Z", "+00:00")
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=ZoneInfo(market.timezone))
    return int(parsed.astimezone(timezone.utc).timestamp())


def _request_params(timeframe: str, *, start_date: str | None, now_ts: int) -> dict:
    config = _PERIODS[timeframe]
    params = {
        "interval": config["interval"],
        "events": "history",
        "includeAdjustedClose": "true",
        "includePrePost": "false",
    }
    if config["lookback_days"] is None:
        if start_date:
            start = int(datetime.strptime(start_date, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp())
        else:
            start = now_ts - 15 * 365 * 86400
        params["period1"] = start
        params["period2"] = now_ts + 2 * 86400
    else:
        params["period1"] = now_ts - int(config["lookback_days"]) * 86400
        params["period2"] = now_ts + 60
    return params


def _is_current_session(ts: int, market: MarketProfile, now_ts: int, regular_start: int | None, regular_end: int | None) -> bool:
    if regular_start is not None and regular_end is not None:
        # Yahoo's regular window can remain today's session after the close.
        return regular_start <= ts <= regular_end and now_ts < regular_end
    try:
        tz = ZoneInfo(market.timezone)
        local = datetime.fromtimestamp(ts, tz=tz)
        current = datetime.fromtimestamp(now_ts, tz=tz)
        if local.date() != current.date() or current.weekday() >= 5:
            return False
        for start, end in market.sessions:
            start_dt = datetime.combine(current.date(), datetime.strptime(start, "%H:%M").time(), tzinfo=tz)
            end_dt = datetime.combine(current.date(), datetime.strptime(end, "%H:%M").time(), tzinfo=tz)
            if start_dt <= local <= end_dt and current <= end_dt:
                return True
    except Exception:
        return False
    return False


def _is_complete(ts: int, timeframe: str, market: MarketProfile, now_ts: int, regular_start: int | None, regular_end: int | None) -> bool:
    if timeframe in {"周线", "月线"}:
        tz = ZoneInfo(market.timezone)
        bar_date = datetime.fromtimestamp(ts, tz=tz).date()
        now_date = datetime.fromtimestamp(now_ts, tz=tz).date()
        same_period = (timeframe == "周线" and bar_date.isocalendar()[:2] == now_date.isocalendar()[:2]) or (
            timeframe == "月线" and bar_date.year == now_date.year and bar_date.month == now_date.month
        )
        # A daily market close does not complete the current week or month.
        return not same_period
    if timeframe == "日线":
        return not _is_current_session(ts, market, now_ts, regular_start, regular_end)
    seconds = int(_PERIODS[timeframe]["seconds"])
    theoretical_end = ts + seconds
    if regular_start is not None and regular_end is not None and regular_start <= ts < regular_end:
        theoretical_end = min(theoretical_end, regular_end)
    return now_ts >= theoretical_end



def _closed_recent_a_share_daily_bar(bar: dict, now_ts: int) -> bool:
    """Only cross-check the latest *closed* daily bar, never historical windows."""
    if not isinstance(bar, dict) or bar.get("time") is None:
        return False
    tz = ZoneInfo(CN_A_SHARE.timezone)
    try:
        session_date = datetime.fromtimestamp(int(bar["time"]), tz=tz).date()
        now = datetime.fromtimestamp(now_ts, tz=tz)
    except (TypeError, ValueError, OverflowError):
        return False
    age = (now.date() - session_date).days
    return 0 <= age <= 7 and now >= datetime.combine(session_date, datetime_time(15, 0), tzinfo=tz)


def _reconcile_closed_a_share_daily_open(bar: dict, quote: dict) -> bool:
    """Correct a bad latest-day open only when independent H/L/C match exactly.

    Yahoo historical bars and Tencent's adjusted historical series can use
    different bases. Never splice Tencent history into a Yahoo window.
    """
    if not isinstance(quote, dict):
        return False
    try:
        quote_date = datetime.strptime(str(quote.get("updated_at") or "")[:8], "%Y%m%d").date()
        bar_date = datetime.fromtimestamp(int(bar["time"]), tz=ZoneInfo(CN_A_SHARE.timezone)).date()
        if quote_date != bar_date:
            return False
        check = {name: float(quote[field]) for name, field in (
            ("open", "open"), ("high", "high"), ("low", "low"), ("close", "price")
        )}
        current = {name: float(bar[name]) for name in ("open", "high", "low", "close")}
    except (KeyError, TypeError, ValueError, OverflowError):
        return False
    if not all(math.isfinite(value) for value in (*check.values(), *current.values())):
        return False
    tolerance = 0.015  # A-share quotations are published to the nearest cent.
    if any(abs(current[name] - check[name]) > tolerance for name in ("high", "low", "close")):
        return False  # Different day, adjustment basis, or quote state; do not mix.
    if not current["low"] - tolerance <= check["open"] <= current["high"] + tolerance:
        return False
    if abs(current["open"] - check["open"]) <= tolerance:
        return False
    bar["open"] = check["open"]
    return True


def _aggregate_hour_bars(ordered: list[dict], market: MarketProfile, factor: int, now_ts: int) -> list[dict]:
    if not ordered:
        return []
    tz = ZoneInfo(market.timezone)
    grouped = {}
    for row in ordered:
        day = datetime.fromtimestamp(row["open_time"], tz=tz).date()
        grouped.setdefault(day, []).append(row)
    result = []
    for day in sorted(grouped):
        rows = sorted(grouped[day], key=lambda item: item["open_time"])
        for offset in range(0, len(rows), factor):
            chunk = rows[offset:offset + factor]
            if not chunk:
                continue
            complete = all(item["complete"] for item in chunk)
            if day == datetime.fromtimestamp(now_ts, tz=tz).date() and len(chunk) < factor:
                complete = complete and any(now_ts >= int((datetime.combine(day, datetime.strptime(end, "%H:%M").time(), tzinfo=tz)).timestamp()) for _, end in market.sessions)
            result.append({
                "date": datetime.fromtimestamp(chunk[0]["open_time"], tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "open_time": chunk[0]["open_time"],
                "open": chunk[0]["open"],
                "high": max(item["high"] for item in chunk),
                "low": min(item["low"] for item in chunk),
                "close": chunk[-1]["close"],
                "volume": sum(item.get("volume") or 0.0 for item in chunk),
                "complete": complete,
            })
    return result


def _parse_chart(payload: dict, symbol: str, timeframe: str, market: MarketProfile, *, now_ts: int, minimum_completed_bars: int = MIN_COMPLETED_BARS):
    chart = payload.get("chart") if isinstance(payload, dict) else None
    error = chart.get("error") if isinstance(chart, dict) else None
    if error:
        raise MarketDataProviderError(f"Yahoo 返回错误：{error}")
    results = chart.get("result") if isinstance(chart, dict) else None
    if not isinstance(results, list) or not results:
        raise MarketDataProviderError(f"{symbol}: Yahoo 行情返回为空")
    result = results[0]
    provider_meta = result.get("meta") or {}
    trading = provider_meta.get("currentTradingPeriod") or {}
    regular = trading.get("regular") or {}
    regular_start = int(regular["start"]) if regular.get("start") is not None else None
    regular_end = int(regular["end"]) if regular.get("end") is not None else None
    timestamps = result.get("timestamp") or []
    quote_rows = (result.get("indicators") or {}).get("quote") or []
    if not quote_rows:
        raise MarketDataProviderError(f"{symbol}: Yahoo 缺少 OHLCV")
    q = quote_rows[0]
    rows = []
    source_timeframe = "60分" if timeframe in {"2小时", "4小时"} else timeframe
    for index, raw_ts in enumerate(timestamps):
        try:
            ts = int(raw_ts)
            values = [_number((q.get(name) or [])[index]) for name in ("open", "high", "low", "close")]
            volume = _number((q.get("volume") or [])[index])
        except (IndexError, TypeError, ValueError):
            continue
        if any(value is None for value in values):
            continue
        rows.append({
            "date": datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "open_time": ts, "open": values[0], "high": values[1], "low": values[2], "close": values[3],
            "volume": volume or 0.0,
            "complete": _is_complete(ts, source_timeframe, market, now_ts, regular_start, regular_end),
        })
    ordered = list({row["open_time"]: row for row in rows}.values())
    ordered.sort(key=lambda item: item["open_time"])
    if timeframe in {"2小时", "4小时"}:
        ordered = _aggregate_hour_bars(ordered, market, int(_PERIODS[timeframe]["factor"]), now_ts)
    def public_bar(row):
        # HuntAlpha's chart/formula contract uses ``time``; SLTD's internal
        # parser calls the same field ``open_time``. Keep both semantics
        # explicit at this adapter boundary without leaking provider naming.
        return {
            **{key: value for key, value in row.items() if key not in {"complete", "open_time"}},
            "time": int(row["open_time"]),
        }

    completed = [public_bar(row) for row in ordered if row["complete"]]
    forming_rows = [row for row in ordered if not row["complete"]]
    forming = None
    if forming_rows:
        forming = public_bar(forming_rows[-1])
    if len(completed) < minimum_completed_bars:
        raise MarketDataProviderError(f"{symbol}: {timeframe} 已完成 K 线不足 {minimum_completed_bars} 根")
    delay_seconds = int(provider_meta.get("exchangeDataDelayedBy") or 0)
    meta = {
        "provider": YAHOO_PROVIDER,
        "provider_label": "Yahoo Finance",
        "exchange_name": provider_meta.get("exchangeName"),
        "exchange_timezone": provider_meta.get("exchangeTimezoneName"),
        "currency": provider_meta.get("currency"),
        "regular_market_start": regular_start,
        "regular_market_end": regular_end,
        "delay_seconds": delay_seconds,
        "data_status": "delayed" if delay_seconds > 0 else "realtime",
        "has_forming_bar": forming is not None,
    }
    return completed, forming, meta


class YahooFinanceMarketDataProvider:
    provider_id = YAHOO_PROVIDER
    provider_label_zh = "Yahoo Finance"

    def __init__(self, market: MarketProfile, *, timeout: int = 18, minimum_completed_bars: int = MIN_COMPLETED_BARS):
        self.profile = market
        self.timeout = timeout
        self.minimum_completed_bars = minimum_completed_bars

    def capabilities(self, market_id=None):
        return {"catalog": False, "quote": True, "history": True, "streaming": False, "polling": True, "public": True, "market": self.profile.market_id}

    def status(self, market_id=None, symbol=None):
        return {"status": "ready", "provider": self.provider_id, "mode": "public", "data_status": "delayed"}

    def _request_chart(self, symbol: str, timeframe: str, *, start_date=None, now_ts=None):
        now_ts = int(now_ts if now_ts is not None else time.time())
        params = urlencode(_request_params(timeframe, start_date=start_date, now_ts=now_ts))
        errors = []
        for host in ("query1.finance.yahoo.com", "query2.finance.yahoo.com"):
            url = f"https://{host}/v8/finance/chart/{quote(yahoo_symbol_for(symbol))}?{params}"
            request = Request(url, headers={"User-Agent": "Mozilla/5.0 (HuntAlpha public market data)", "Accept": "application/json,text/plain,*/*"})
            try:
                with urlopen(request, timeout=self.timeout) as response:
                    return json.loads(response.read().decode("utf-8"))
            except (HTTPError, URLError, TimeoutError, OSError, ValueError) as exc:
                errors.append(f"{host}:{type(exc).__name__}")
        raise MarketDataProviderError("Yahoo Finance 请求失败：" + ";".join(errors))

    def fetch_window(self, symbol: str, timeframe: str, **kwargs):
        if timeframe not in _PERIODS:
            raise MarketDataProviderError(f"Yahoo 不支持周期：{timeframe}")
        now_ts = int(kwargs.get("now_ts") or time.time())
        payload = self._request_chart(symbol, timeframe, start_date=kwargs.get("start_date"), now_ts=now_ts)
        completed, forming, meta = _parse_chart(payload, str(symbol).upper(), timeframe, self.profile, now_ts=now_ts, minimum_completed_bars=int(kwargs.get("minimum_completed_bars", self.minimum_completed_bars)))
        if (self.profile.market_id == CN_A_SHARE.market_id and timeframe == "日线"
                and not kwargs.get("before") and completed
                and _closed_recent_a_share_daily_bar(completed[-1], now_ts)):
            # Validate against a *same-session* independent daily quote.
            # A failed quote must not replace the original complete window.
            try:
                from .tencent import TencentPublicMarketDataProvider
                check_quote = TencentPublicMarketDataProvider(CN_A_SHARE, timeout=3).quote(symbol)
                if _reconcile_closed_a_share_daily_open(completed[-1], check_quote):
                    meta["daily_open_crosscheck"] = "corrected_from_tencent_quote"
            except Exception:
                pass
        meta.update({"source": "network", "mode": "historical", "adjustment": "Yahoo adjusted close"})
        return {"completed": completed, "forming": forming, "meta": meta}

    def fetch_recent(self, symbol, timeframe, **kwargs):
        return self.fetch_window(symbol, timeframe, **kwargs)

    def quote(self, symbol: str):
        payload = self._request_chart(symbol, "日线", now_ts=int(time.time()))
        chart = payload.get("chart") or {}
        result = (chart.get("result") or [None])[0] or {}
        meta = result.get("meta") or {}
        q = ((result.get("indicators") or {}).get("quote") or [{}])[0]
        closes = q.get("close") or []
        price = _number(meta.get("regularMarketPrice")) or next((_number(value) for value in reversed(closes) if _number(value) is not None), None)
        if price is None:
            raise MarketDataProviderError("Yahoo 未返回真实报价")
        previous = _number(meta.get("previousClose"))
        if previous is None:
            previous = _recent_previous_close(price, closes)
        if previous is None:
            # This is only a last-resort provider field. It is intentionally
            # not preferred because long-range chartPreviousClose can be the
            # first close in the requested history window.
            previous = _number(meta.get("chartPreviousClose"))
        provider_change = _number(meta.get("regularMarketChangePercent"))
        change = provider_change if provider_change is not None else ((price - previous) / previous * 100) if previous else None
        delay_seconds = int(meta.get("exchangeDataDelayedBy") or 0)
        updated = meta.get("regularMarketTime")
        return {
            "code": str(symbol).upper(), "price": price, "change": round(change, 3) if change is not None else None,
            "previous_close": previous, "open": _number(meta.get("regularMarketOpen")),
            "high": _number(meta.get("regularMarketDayHigh")), "low": _number(meta.get("regularMarketDayLow")),
            "volume": _number(meta.get("regularMarketVolume")), "updated_at": updated,
            "source": self.provider_id, "status": "ready", "data_status": "delayed" if delay_seconds > 0 else "realtime",
            "delay_seconds": delay_seconds,
        }

    def list_securities(self, market_id, query="", page=1):
        raise MarketDataProviderError("Yahoo 公开行情不提供完整证券目录", status="unavailable")

    def subscribe(self, symbol, timeframe, callback):
        raise MarketDataProviderError("Yahoo 公开行情通过统一轮询实时 Provider 更新", status="unavailable")

    def unsubscribe(self, symbol, timeframe):
        return {"status": "unsupported", "provider": self.provider_id}
