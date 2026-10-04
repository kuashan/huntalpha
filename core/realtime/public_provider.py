from __future__ import annotations

import os
import threading
import time
from collections import defaultdict
from datetime import datetime, timezone

from .contracts import NormalizedBar, market_for_symbol, optional_numeric
from .provider import REALTIME_PERIOD_SUBTYPES, RealtimeMarketProvider, RealtimeProviderError


_PERIOD_SECONDS = {
    "1分": 60, "5分": 300, "15分": 900, "30分": 1800, "60分": 3600,
    "2小时": 7200, "4小时": 14400, "日线": 86400, "周线": 7 * 86400, "月线": 31 * 86400,
}


def _timestamp(value):
    if isinstance(value, (int, float)):
        return int(value)
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return int(parsed.astimezone(timezone.utc).timestamp())


class PublicMarketRealtimeProvider(RealtimeMarketProvider):
    """Polling realtime facade over the public MarketDataRouter.

    Public providers may expose delayed quotes.  The event retains the
    selected provider and ``data_status`` so the browser never labels a
    delayed public quote as live.  No synthetic bar is generated on failure.
    """

    provider_name = "public-market"
    supported_markets = frozenset({"cn", "hk", "us"})

    def __init__(self, market_router, *, poll_interval: float | None = None):
        self.market_router = market_router
        self.poll_interval = max(2.0, float(poll_interval or os.environ.get("PUBLIC_REALTIME_POLL_SECONDS", "15")))
        self._callbacks = defaultdict(set)
        self._sequences = defaultdict(int)
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._thread = None
        self._status = "ready"

    @property
    def status(self):
        with self._lock:
            return self._status

    def supports_symbol(self, symbol):
        return market_for_symbol(symbol) in self.supported_markets

    def capabilities(self):
        return {
            "streaming": False,
            "polling": True,
            "public": True,
            "markets": tuple(sorted(self.supported_markets)),
            "periods": tuple(_PERIOD_SECONDS),
            "provider": self.provider_name,
        }

    def _quote(self, symbol):
        market = market_for_symbol(symbol)
        if market not in self.supported_markets:
            raise RealtimeProviderError(f"公开行情不支持市场：{market or 'unknown'}", status="unavailable")
        market_id = {"cn": "CN_A_SHARE", "hk": "HK_EQUITY", "us": "US_EQUITY"}[market]
        return self.market_router.quote(market_id, symbol)

    def _normalize_quote(self, symbol, period, quote):
        market = market_for_symbol(symbol)
        now = int(time.time())
        stamp = _timestamp(quote.get("updated_at")) or now
        seconds = _PERIOD_SECONDS[period]
        bucket = stamp - (stamp % seconds)
        key = (str(symbol).upper(), period)
        with self._lock:
            self._sequences[key] += 1
            sequence = self._sequences[key]
        price = optional_numeric(quote.get("price"))
        open_value = optional_numeric(quote.get("open")) or price
        high = optional_numeric(quote.get("high")) or price
        low = optional_numeric(quote.get("low")) or price
        if price is None or open_value is None or high is None or low is None:
            raise RealtimeProviderError("公开行情报价缺少有效 OHLC", status="unavailable")
        return NormalizedBar(
            provider=str(quote.get("source") or self.provider_name), market=market,
            symbol=str(symbol).upper(), period=period, time=bucket,
            open=open_value, high=high, low=low, close=price,
            volume=optional_numeric(quote.get("volume")), amount=optional_numeric(quote.get("amount")),
            is_closed=False, provider_timestamp=stamp, sequence=sequence,
            revision=0, mode="polling", event_kind="live",
            data_status=str(quote.get("data_status") or "delayed"),
        )

    def _emit_status(self, symbol, period, status, error=None):
        payload = {
            "status": status, "source": self.provider_name, "provider": self.provider_name,
            "market": market_for_symbol(symbol), "symbol": str(symbol).upper(),
            "period": period, "mode": "polling", "data_status": "unavailable",
        }
        if error:
            payload["error"] = error
        with self._lock:
            callbacks = list(self._callbacks.get((str(symbol).upper(), period), set()))
        for callback in callbacks:
            callback(payload)

    def poll_once(self):
        with self._lock:
            subscriptions = [(key, list(callbacks)) for key, callbacks in self._callbacks.items()]
        for (symbol, period), callbacks in subscriptions:
            try:
                bar = self._normalize_quote(symbol, period, self._quote(symbol))
            except RealtimeProviderError as exc:
                self._emit_status(symbol, period, exc.status, str(exc))
                continue
            except Exception as exc:
                self._emit_status(symbol, period, "unavailable", str(exc))
                continue
            with self._lock:
                self._status = "polling"
            for callback in callbacks:
                callback(bar)

    def _run(self):
        while not self._stop.is_set():
            self.poll_once()
            self._stop.wait(self.poll_interval)

    def subscribe(self, symbol, period, callback):
        if not self.supports_symbol(symbol):
            raise RealtimeProviderError("公开实时轮询仅支持股票市场", status="unavailable")
        if period not in REALTIME_PERIOD_SUBTYPES or period not in _PERIOD_SECONDS:
            raise RealtimeProviderError(f"公开实时轮询不支持周期：{period}", status="unavailable")
        key = (str(symbol).upper(), str(period))
        with self._lock:
            self._callbacks[key].add(callback)
            if self._thread is None or not self._thread.is_alive():
                self._stop.clear()
                self._thread = threading.Thread(target=self._run, name="huntalpha-public-poll", daemon=True)
                self._thread.start()
        self._emit_status(symbol, period, "polling")

    def unsubscribe(self, symbol, period):
        key = (str(symbol).upper(), str(period))
        with self._lock:
            self._callbacks.pop(key, None)
            if not self._callbacks:
                self._stop.set()

    def latest_snapshot(self, symbol, period):
        if period not in _PERIOD_SECONDS:
            raise RealtimeProviderError(f"公开实时轮询不支持周期：{period}", status="unavailable")
        return self._normalize_quote(symbol, period, self._quote(symbol))

    def health_check(self):
        with self._lock:
            if not self._callbacks:
                return self._status
            return "polling" if self._thread is not None and self._thread.is_alive() else "reconnecting"

    def close(self):
        self._stop.set()
        with self._lock:
            thread = self._thread
            self._thread = None
            self._callbacks.clear()
            self._status = "unavailable"
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=1)
