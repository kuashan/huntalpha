from __future__ import annotations

from datetime import datetime, timezone
import os
from typing import Any

from ..profiles import HK_EQUITY, US_EQUITY
from .base import MarketDataProviderError, unavailable_status


LONGBRIDGE_PROVIDER = "longbridge"
_PERIOD_NAMES = {"1分": "Minute", "5分": "FiveMinute", "15分": "FifteenMinute", "30分": "ThirtyMinute", "60分": "Hour", "2小时": "TwoHour", "4小时": "FourHour", "日线": "Day", "周线": "Week", "月线": "Month"}


def provider_symbol_for(symbol: str) -> str:
    normalized = str(symbol or "").strip().upper()
    prefix, separator, body = normalized.partition(".")
    if separator and prefix in {"SH", "SZ", "HK", "US"}:
        if prefix == "HK":
            body = body.lstrip("0") or "0"
        return f"{body}.{prefix}"
    return normalized


def _stamp(value: Any) -> int | None:
    if isinstance(value, (int, float)):
        return int(value)
    if hasattr(value, "timestamp") and callable(value.timestamp):
        return int(value.timestamp())
    text = str(value or "").strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return int(parsed.astimezone(timezone.utc).timestamp())


def _attr(row: Any, *names: str):
    if isinstance(row, dict):
        for name in names:
            if name in row:
                return row[name]
    for name in names:
        if hasattr(row, name):
            return getattr(row, name)
    return None


class LongbridgeMarketDataProvider:
    provider_id = LONGBRIDGE_PROVIDER
    provider_label_zh = "Longbridge"

    def __init__(self, token: str | None = None, context: Any = None, market=HK_EQUITY):
        self.token = (token or os.environ.get("LONGBRIDGE_ACCESS_TOKEN", "")).strip()
        self.context = context
        self.profile = market

    def _context_or_raise(self):
        if self.context is not None:
            return self.context
        if not self.token:
            raise MarketDataProviderError("Longbridge access token 未配置", status="not_configured")
        try:
            from longbridge.openapi import Config, QuoteContext
            self.context = QuoteContext(Config.from_apikey_env())
        except ImportError as exc:
            raise MarketDataProviderError("Longbridge SDK 未安装", status="unavailable") from exc
        except Exception as exc:
            raise MarketDataProviderError("Longbridge 行情上下文初始化失败", status="unavailable") from exc
        return self.context

    def capabilities(self, market_id: str | None = None) -> dict[str, Any]:
        return {"catalog": True, "quote": True, "history": True, "streaming": self.context is not None, "market": self.profile.market_id}

    def status(self, market_id: str | None = None, symbol: str | None = None) -> dict[str, Any]:
        if self.context is None and not self.token:
            return unavailable_status(self.provider_id, reason="not_configured", detail="LONGBRIDGE_ACCESS_TOKEN 未配置")
        return {"status": "ready", "provider": self.provider_id, "mode": "historical"}

    def quote(self, symbol: str) -> dict:
        rows = self._context_or_raise().quote([provider_symbol_for(symbol)])
        if not rows:
            raise MarketDataProviderError("Longbridge 未返回真实报价", status="unavailable")
        row = rows[0]
        price = _attr(row, "last_done", "last", "price")
        if price is None:
            raise MarketDataProviderError("Longbridge 报价缺少最新价", status="unavailable")
        return {"code": str(symbol).upper(), "price": float(price), "volume": _attr(row, "volume"), "amount": _attr(row, "turnover"), "source": self.provider_id, "status": "ready"}

    def fetch_window(self, symbol: str, timeframe: str, **kwargs: Any) -> dict:
        # Resolve credentials before probing the optional SDK so an absent
        # provider is reported as not_configured rather than as an SDK error.
        context = self._context_or_raise()
        try:
            from longbridge.openapi import AdjustType, Period
            period = getattr(Period, _PERIOD_NAMES.get(timeframe, "Day"))
            adjust = AdjustType.NoAdjust
        except ImportError as exc:
            # Injected contexts keep contract tests and controlled adapters
            # usable without installing the optional SDK. A real context is
            # still required before any network request can occur.
            if self.context is None:
                raise MarketDataProviderError("Longbridge SDK 未安装") from exc
            period, adjust = timeframe, None
        count = int(kwargs.get("limit", 300))
        rows = context.candlesticks(provider_symbol_for(symbol), period, adjust, count)
        completed = []
        for row in rows or []:
            stamp = _stamp(_attr(row, "timestamp", "time"))
            values = {key: _attr(row, key) for key in ("open", "high", "low", "close", "volume", "turnover")}
            if stamp is None or any(values[key] is None for key in ("open", "high", "low", "close")):
                continue
            completed.append({"provider": self.provider_id, "market": self.profile.market_id, "symbol": str(symbol).upper(), "period": timeframe, "time": stamp, "open": float(values["open"]), "high": float(values["high"]), "low": float(values["low"]), "close": float(values["close"]), "volume": float(values["volume"]) if values["volume"] is not None else None, "amount": float(values["turnover"]) if values["turnover"] is not None else None, "is_closed": True, "timestamp": stamp, "sequence": None, "revision": 0, "mode": "historical"})
        completed.sort(key=lambda item: item["time"])
        return {"completed": completed, "forming": None, "meta": {"mode": "historical", "source": self.provider_id}}

    def fetch_recent(self, symbol: str, timeframe: str, **kwargs: Any) -> dict:
        return self.fetch_window(symbol, timeframe, **kwargs)

    def list_securities(self, market_id: str, query: str = "", page: int = 1) -> list[dict]:
        raise MarketDataProviderError("Longbridge 全市场目录需要按市场分页配置")

    def subscribe(self, symbol: str, timeframe: str, callback):
        raise MarketDataProviderError("Longbridge 实时能力由统一实时 Provider 提供", status="unavailable")

    def unsubscribe(self, symbol: str, timeframe: str):
        return {"status": "unsupported", "provider": self.provider_id}
