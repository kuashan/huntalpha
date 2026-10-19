from __future__ import annotations

import os
import threading
from collections import defaultdict

from .contracts import NormalizedBar, market_for_symbol, optional_numeric
from .provider import REALTIME_PERIOD_SUBTYPES, RealtimeMarketProvider, RealtimeProviderError


# A public quote contains daily aggregates, not candles for arbitrary periods.
# Reuse the same full-window provider as /api/kline so the timestamps/OHLC agree.
_MARKET_IDS = {"cn": "CN_A_SHARE", "hk": "HK_EQUITY", "us": "US_EQUITY"}
_MIN_POLL_SECONDS = 60.0


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
        self.poll_interval = max(_MIN_POLL_SECONDS, float(poll_interval or os.environ.get("PUBLIC_REALTIME_POLL_SECONDS", "60")))
        self._callbacks = defaultdict(set)
        self._last_emitted = {}
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
            "periods": tuple(REALTIME_PERIOD_SUBTYPES),
            "provider": self.provider_name,
        }

    def _period_bar(self, symbol, period):
        market = market_for_symbol(symbol)
        if market not in self.supported_markets:
            raise RealtimeProviderError(f"公开行情不支持市场：{market or 'unknown'}", status="unavailable")
        fetch = self.market_router.fetch_window(_MARKET_IDS[market], symbol, period)
        # The router may return a stale cached window when every source fails.
        # That is valid historical fallback but must not be emitted as live data.
        if fetch.meta.get("stale") or fetch.meta.get("mode") == "cache":
            raise RealtimeProviderError("仅有缓存行情，不能作为实时 K 线", status="unavailable")
        forming = fetch.forming
        source = forming if forming is not None else (fetch.completed[-1] if fetch.completed else None)
        if not isinstance(source, dict):
            raise RealtimeProviderError("行情源没有返回真实周期 K 线", status="unavailable")
        stamp = source.get("time")
        try:
            stamp = int(stamp) if stamp is not None else None
        except (TypeError, ValueError, OverflowError):
            stamp = None
        values = {name: optional_numeric(source.get(name)) for name in ("open", "high", "low", "close")}
        if stamp is None or any(value is None for value in values.values()):
            raise RealtimeProviderError("周期 K 线缺少有效时间或 OHLC", status="unavailable")
        return NormalizedBar(
            provider=fetch.provider_id, market=market,
            symbol=str(symbol).upper(), period=period, time=stamp,
            open=values["open"], high=values["high"], low=values["low"], close=values["close"],
            volume=optional_numeric(source.get("volume")), amount=optional_numeric(source.get("amount")),
            is_closed=forming is None, provider_timestamp=stamp, sequence=None,
            revision=0, mode="polling", event_kind="authoritative",
            data_status=str(fetch.meta.get("data_status") or "historical"),
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
                bar = self._period_bar(symbol, period)
            except RealtimeProviderError as exc:
                self._emit_status(symbol, period, exc.status, str(exc))
                continue
            except Exception as exc:
                self._emit_status(symbol, period, "unavailable", str(exc))
                continue
            # An unchanged last candle is not a new tick. Avoid repeated
            # formula refreshes and SSE traffic while the exchange is closed.
            fingerprint = (bar.provider, bar.time, bar.open, bar.high, bar.low, bar.close,
                           bar.volume, bar.amount, bar.is_closed, bar.data_status)
            with self._lock:
                self._status = "polling"
                if self._last_emitted.get((symbol, period)) == fingerprint:
                    continue
                self._last_emitted[(symbol, period)] = fingerprint
            for callback in callbacks:
                callback(bar)

    def _run(self):
        while not self._stop.is_set():
            self.poll_once()
            self._stop.wait(self.poll_interval)

    def subscribe(self, symbol, period, callback):
        if not self.supports_symbol(symbol):
            raise RealtimeProviderError("公开实时轮询仅支持股票市场", status="unavailable")
        if period not in REALTIME_PERIOD_SUBTYPES:
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
            self._last_emitted.pop(key, None)
            if not self._callbacks:
                self._stop.set()

    def latest_snapshot(self, symbol, period):
        if period not in REALTIME_PERIOD_SUBTYPES:
            raise RealtimeProviderError(f"公开实时轮询不支持周期：{period}", status="unavailable")
        return self._period_bar(symbol, period)

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
            self._last_emitted.clear()
            self._status = "unavailable"
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=1)
