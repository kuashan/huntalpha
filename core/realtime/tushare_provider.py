from __future__ import annotations

import os
import threading
import time
from collections import defaultdict
from typing import Any

from .contracts import NormalizedBar, market_for_symbol, optional_numeric, provider_time_to_timestamp
from .provider import REALTIME_PERIOD_SUBTYPES, RealtimeMarketProvider, RealtimeProviderError


TUSHARE_REALTIME_PROVIDER = "tushare"
_PERIOD_FREQ = {
    "1分": "1min", "5分": "5min", "15分": "15min", "30分": "30min", "60分": "60min",
    "2小时": "120min", "4小时": "240min", "日线": "D", "周线": "W", "月线": "M",
}


def provider_symbol_for(symbol: str) -> str:
    normalized = str(symbol or "").strip().upper()
    prefix, separator, body = normalized.partition(".")
    if not separator or prefix not in {"SH", "SZ"} or not body:
        raise RealtimeProviderError(f"Tushare 不支持证券代码：{symbol}")
    return f"{body}.{prefix}"


def _attr(value: Any, *names: str):
    if isinstance(value, dict):
        for name in names:
            if name in value:
                return value[name]
    for name in names:
        if hasattr(value, name):
            return getattr(value, name)
    return None


class TushareRealtimeProvider(RealtimeMarketProvider):
    """Provider-neutral polling adapter for Tushare real/near-real-time APIs."""

    provider_name = TUSHARE_REALTIME_PROVIDER
    supported_markets = frozenset({"cn"})

    def __init__(self, token: str | None = None, client: Any = None, poll_interval: float | None = None):
        self.token = (token or os.environ.get("TUSHARE_TOKEN", "")).strip()
        self.client = client
        self.poll_interval = max(0.5, float(poll_interval or os.environ.get("TUSHARE_REALTIME_POLL_SECONDS", "5")))
        self._callbacks = defaultdict(set)
        self._symbols = {}
        self._sequences = defaultdict(int)
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._thread = None
        self._status = "ready" if (self.token or self.client is not None) else "not_configured"

    @property
    def status(self):
        with self._lock:
            return self._status

    @property
    def provider_id(self):
        return self.provider_name

    def supports_symbol(self, symbol: str) -> bool:
        return market_for_symbol(symbol) == "cn"

    def _client_or_raise(self):
        if self.client is not None:
            return self.client
        if not self.token:
            with self._lock:
                self._status = "not_configured"
            raise RealtimeProviderError("Tushare 实时行情未配置", status="not_configured")
        try:
            import tushare as ts
        except ImportError as exc:
            with self._lock:
                self._status = "unavailable"
            raise RealtimeProviderError("Tushare SDK 未安装", status="unavailable") from exc
        ts.set_token(self.token)
        self.client = ts.pro_api(self.token)
        return self.client

    def capabilities(self):
        return {
            "streaming": False,
            "polling": True,
            "markets": ("cn",),
            "periods": tuple(_PERIOD_FREQ),
            "provider": self.provider_name,
        }

    def _rows(self, payload):
        if payload is None:
            return []
        if hasattr(payload, "to_dict"):
            try:
                return list(payload.to_dict("records"))
            except TypeError:
                pass
        if isinstance(payload, dict):
            return [payload]
        if isinstance(payload, (list, tuple)):
            return [row if isinstance(row, dict) else vars(row) for row in payload]
        return []

    def _fetch_latest_row(self, symbol, period):
        client = self._client_or_raise()
        provider_symbol = provider_symbol_for(symbol)
        realtime = getattr(client, "realtime_quote", None)
        if callable(realtime):
            try:
                payload = realtime(provider_symbol, period)
            except TypeError:
                payload = realtime([provider_symbol])
            rows = self._rows(payload)
        else:
            pro_bar = getattr(client, "pro_bar", None)
            if not callable(pro_bar):
                raise RealtimeProviderError("Tushare 客户端不支持实时轮询接口", status="unavailable")
            try:
                payload = pro_bar(ts_code=provider_symbol, freq=_PERIOD_FREQ.get(period, period), adj="qfq")
            except Exception as exc:
                raise RealtimeProviderError(f"Tushare 实时轮询失败：{type(exc).__name__}", status="unavailable") from exc
            rows = self._rows(payload)
        if not rows:
            raise RealtimeProviderError("Tushare 未返回实时行情", status="unavailable")
        return max(rows, key=lambda row: str(_attr(row, "trade_time", "timestamp", "trade_date") or ""))

    def _normalize_row(self, symbol, period, row):
        trade_time = _attr(row, "trade_time", "timestamp", "time", "trade_date")
        timestamp = provider_time_to_timestamp(trade_time, "cn")
        values = {name: optional_numeric(_attr(row, name)) for name in ("open", "high", "low", "close")}
        volume = optional_numeric(_attr(row, "vol", "volume"))
        amount = optional_numeric(_attr(row, "amount", "turnover"))
        if timestamp is None or any(values[name] is None for name in values):
            raise RealtimeProviderError("Tushare 实时行情缺少有效 OHLCV", status="unavailable")
        key = (str(symbol).upper(), period)
        with self._lock:
            self._sequences[key] += 1
            sequence = self._sequences[key]
        return NormalizedBar(
            provider=self.provider_name,
            market="cn",
            symbol=str(symbol).upper(),
            period=period,
            time=timestamp,
            open=values["open"], high=values["high"], low=values["low"], close=values["close"],
            volume=volume, amount=amount, turnover_rate=None,
            is_closed=False, provider_timestamp=timestamp, sequence=sequence,
            revision=0, mode="polling", event_kind="live",
        )

    def poll_once(self):
        with self._lock:
            subscriptions = [(key, list(callbacks)) for key, callbacks in self._callbacks.items()]
        for (symbol, period), callbacks in subscriptions:
            try:
                bar = self._normalize_row(symbol, period, self._fetch_latest_row(symbol, period))
            except RealtimeProviderError as exc:
                self._emit_status(symbol, period, exc.status, str(exc))
                continue
            with self._lock:
                self._status = "polling"
            for callback in callbacks:
                callback(bar)

    def _run(self):
        while not self._stop.is_set():
            self.poll_once()
            self._stop.wait(self.poll_interval)

    def _emit_status(self, symbol, period, status, error=None):
        payload = {
            "status": status,
            "source": self.provider_name,
            "provider": self.provider_name,
            "market": "cn",
            "symbol": str(symbol).upper(),
            "period": period,
            "mode": "polling",
        }
        if error:
            payload["error"] = error
        with self._lock:
            callbacks = list(self._callbacks.get((str(symbol).upper(), period), set()))
        for callback in callbacks:
            callback(payload)

    def subscribe(self, symbol, period, callback):
        if not self.supports_symbol(symbol):
            raise RealtimeProviderError("Tushare 仅支持 A 股实时轮询", status="unavailable")
        if period not in REALTIME_PERIOD_SUBTYPES or period not in _PERIOD_FREQ:
            raise RealtimeProviderError(f"Tushare 不支持周期：{period}", status="unavailable")
        self._client_or_raise()
        key = (str(symbol).upper(), str(period))
        with self._lock:
            self._callbacks[key].add(callback)
            self._symbols[key] = str(symbol).upper()
            self._status = "polling"
            if self._thread is None or not self._thread.is_alive():
                self._stop.clear()
                self._thread = threading.Thread(target=self._run, name="huntalpha-tushare-poll", daemon=True)
                self._thread.start()
        self._emit_status(symbol, period, "polling")
        return None

    def unsubscribe(self, symbol, period):
        key = (str(symbol).upper(), str(period))
        with self._lock:
            self._callbacks.pop(key, None)
            self._symbols.pop(key, None)
            if not self._callbacks:
                self._stop.set()

    def latest_snapshot(self, symbol, period):
        return self._normalize_row(symbol, period, self._fetch_latest_row(symbol, period))

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
            self._symbols.clear()
            self._status = "unavailable"
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=1)
