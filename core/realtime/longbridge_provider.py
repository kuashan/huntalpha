from __future__ import annotations

import os
import threading
from collections import defaultdict
from typing import Any

from .contracts import NormalizedBar, market_for_symbol, optional_numeric, provider_time_to_timestamp
from .provider import REALTIME_PERIOD_SUBTYPES, RealtimeMarketProvider, RealtimeProviderError


LONGBRIDGE_REALTIME_PROVIDER = "longbridge"

_PERIOD_NAMES = {
    "1分": "Min_1",
    "5分": "Min_5",
    "15分": "Min_15",
    "30分": "Min_30",
    "60分": "Min_60",
    "2小时": "Min_120",
    "4小时": "Min_240",
    "日线": "Day",
    "周线": "Week",
    "月线": "Month",
}
_PERIOD_BY_PROVIDER_NAME = {value: key for key, value in _PERIOD_NAMES.items()}


def _attr(value: Any, *names: str):
    if isinstance(value, dict):
        for name in names:
            if name in value:
                return value[name]
    for name in names:
        if hasattr(value, name):
            return getattr(value, name)
    return None


def provider_symbol_for(symbol: str) -> str:
    """Convert HuntAlpha's PREFIX.CODE form to Longbridge CODE.REGION."""
    normalized = str(symbol or "").strip().upper()
    prefix, separator, body = normalized.partition(".")
    if not separator or not body or prefix not in {"SH", "SZ", "HK", "US"}:
        raise RealtimeProviderError(f"Longbridge 不支持证券代码：{symbol}")
    if prefix == "HK":
        body = body.lstrip("0") or "0"
    return f"{body}.{prefix}"


def _provider_period_name(value: Any) -> str | None:
    name = _attr(value, "name")
    if name:
        return str(name).split(".")[-1]
    text = str(value or "").split(".")[-1]
    return text or None


class LongbridgeRealtimeProvider(RealtimeMarketProvider):
    """Longbridge candlestick push adapter behind the shared realtime contract."""

    provider_name = LONGBRIDGE_REALTIME_PROVIDER
    supported_markets = frozenset({"hk", "us"})

    def __init__(self, token: str | None = None, context: Any = None, supported_markets=None):
        self.token = (token or os.environ.get("LONGBRIDGE_ACCESS_TOKEN", "")).strip()
        self.context = context
        configured_markets = os.environ.get("LONGBRIDGE_MARKETS", "hk,us")
        self.supported_markets = frozenset(
            supported_markets or {item.strip().lower() for item in configured_markets.split(",") if item.strip()}
        )
        self._callbacks = defaultdict(set)
        self._bars = {}
        self._symbols = {}
        self._sequences = defaultdict(int)
        self._handler_registered = False
        self._lock = threading.RLock()
        self._status = "live" if context is not None else ("ready" if self.token else "not_configured")

    @property
    def status(self):
        with self._lock:
            return self._status

    @property
    def provider_id(self):
        return self.provider_name

    def supports_symbol(self, symbol: str) -> bool:
        return market_for_symbol(symbol) in self.supported_markets

    def _context_or_raise(self):
        if self.context is not None:
            return self.context
        if not self.token:
            with self._lock:
                self._status = "not_configured"
            raise RealtimeProviderError("Longbridge 实时行情未配置", status="not_configured")
        try:
            from longbridge.openapi import Config, QuoteContext
            self.context = QuoteContext(Config.from_apikey_env())
        except ImportError as exc:
            with self._lock:
                self._status = "unavailable"
            raise RealtimeProviderError("Longbridge SDK 未安装", status="unavailable") from exc
        except Exception as exc:
            with self._lock:
                self._status = "unavailable"
            raise RealtimeProviderError("Longbridge 行情上下文初始化失败", status="unavailable") from exc
        return self.context

    def _period_value(self, period: str):
        name = _PERIOD_NAMES.get(str(period).strip())
        if not name:
            raise RealtimeProviderError(f"Longbridge 不支持周期：{period}")
        try:
            from longbridge.openapi import Period
            return getattr(Period, name)
        except ImportError:
            # Tests and controlled adapters may inject a context without the optional SDK.
            return name

    def _register_handler(self, context):
        if self._handler_registered:
            return
        setter = getattr(context, "set_on_candlestick", None)
        if not callable(setter):
            raise RealtimeProviderError("Longbridge 上下文不支持 K 线回调", status="unavailable")
        setter(self._on_candlestick)
        self._handler_registered = True

    def capabilities(self):
        return {
            "streaming": bool(self.context is not None or self.token),
            "markets": tuple(sorted(self.supported_markets)),
            "periods": tuple(_PERIOD_NAMES),
            "provider": self.provider_name,
        }

    def subscribe(self, symbol, period, callback):
        if not self.supports_symbol(symbol):
            raise RealtimeProviderError(f"Longbridge 未配置市场：{market_for_symbol(symbol)}", status="unavailable")
        provider_symbol = provider_symbol_for(symbol)
        normalized_period = str(period).strip()
        period_value = self._period_value(normalized_period)
        context = self._context_or_raise()
        self._register_handler(context)
        key = (provider_symbol, normalized_period)
        with self._lock:
            first = not self._callbacks[key]
            self._callbacks[key].add(callback)
            self._symbols[key] = str(symbol).upper()
        if not first:
            return None
        try:
            context.subscribe_candlesticks(provider_symbol, period_value)
        except Exception as exc:
            with self._lock:
                self._callbacks[key].discard(callback)
                if not self._callbacks[key]:
                    self._callbacks.pop(key, None)
                    self._symbols.pop(key, None)
                self._status = "unavailable"
            raise RealtimeProviderError(f"Longbridge 实时订阅失败：{type(exc).__name__}", status="unavailable") from exc
        with self._lock:
            self._status = "live"
        return None

    def unsubscribe(self, symbol, period):
        provider_symbol = provider_symbol_for(symbol)
        normalized_period = str(period).strip()
        period_value = self._period_value(normalized_period)
        key = (provider_symbol, normalized_period)
        with self._lock:
            self._callbacks.pop(key, None)
            self._symbols.pop(key, None)
        if self.context is not None:
            try:
                self.context.unsubscribe_candlesticks(provider_symbol, period_value)
            except Exception:
                pass

    def _normalize_candle(self, symbol, period, candle, *, is_closed=False):
        market = market_for_symbol(symbol)
        timestamp = provider_time_to_timestamp(_attr(candle, "timestamp", "time"), market)
        values = {
            name: optional_numeric(_attr(candle, name))
            for name in ("open", "high", "low", "close", "volume", "turnover")
        }
        if timestamp is None or any(values[name] is None for name in ("open", "high", "low", "close")):
            return None
        key = (provider_symbol_for(symbol), period)
        with self._lock:
            self._sequences[key] += 1
            sequence = self._sequences[key]
        return NormalizedBar(
            provider=self.provider_name,
            market=market or "unknown",
            symbol=str(symbol).upper(),
            period=period,
            time=timestamp,
            open=values["open"], high=values["high"], low=values["low"], close=values["close"],
            volume=values["volume"], amount=values["turnover"], turnover_rate=None,
            is_closed=bool(is_closed), provider_timestamp=timestamp, sequence=sequence,
            revision=0, mode="streaming", event_kind="live",
        )

    def _on_candlestick(self, provider_symbol: str, event: Any):
        event_period = _PERIOD_BY_PROVIDER_NAME.get(_provider_period_name(_attr(event, "period")))
        candle = _attr(event, "candlestick") or event
        confirmed = bool(_attr(event, "is_confirmed"))
        with self._lock:
            keys = [key for key in self._callbacks if key[0] == provider_symbol and (event_period is None or key[1] == event_period)]
            callbacks = [(key, list(self._callbacks[key])) for key in keys]
        for (key, listeners) in callbacks:
            with self._lock:
                active_symbol = self._symbols.get(key)
            if active_symbol is None:
                continue
            bar = self._normalize_candle(active_symbol, key[1], candle, is_closed=confirmed)
            if bar is None:
                continue
            with self._lock:
                self._bars[key] = bar
            for listener in listeners:
                listener(bar)

    def latest_snapshot(self, symbol, period):
        context = self._context_or_raise()
        provider_symbol = provider_symbol_for(symbol)
        period_value = self._period_value(period)
        getter = getattr(context, "realtime_candlesticks", None)
        if not callable(getter):
            return None
        try:
            rows = getter(provider_symbol, period_value, 2) or []
        except Exception as exc:
            raise RealtimeProviderError(f"Longbridge 实时快照失败：{type(exc).__name__}", status="unavailable") from exc
        candle = rows[-1] if rows else None
        return self._normalize_candle(symbol, period, candle, is_closed=False) if candle is not None else None

    def health_check(self):
        with self._lock:
            if not self._callbacks:
                return self._status
            return "live" if self.context is not None and self._status == "live" else self._status

    def close(self):
        with self._lock:
            self._callbacks.clear()
            self._bars.clear()
            self._symbols.clear()
            context = self.context
            self.context = None
            self._handler_registered = False
            self._status = "unavailable"
        if context is not None:
            try:
                context.close()
            except Exception:
                pass
