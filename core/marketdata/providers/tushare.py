from __future__ import annotations

from datetime import datetime, timezone
import os
from typing import Any
from zoneinfo import ZoneInfo

from ..profiles import CN_A_SHARE
from .base import MarketDataProviderError, unavailable_status


TUSHARE_PROVIDER = "tushare"
_PERIODS = {
    "1分": "1min",
    "5分": "5min",
    "15分": "15min",
    "30分": "30min",
    "60分": "60min",
    "日线": "D",
    "周线": "W",
    "月线": "M",
    "1d": "D",
    "day": "D",
    "week": "W",
    "month": "M",
}


def _records(frame: Any) -> list[dict]:
    if frame is None:
        return []
    if hasattr(frame, "to_dict"):
        try:
            return list(frame.to_dict("records"))
        except TypeError:
            pass
    if hasattr(frame, "itertuples"):
        rows = []
        for row in frame.itertuples(index=False):
            rows.append(row._asdict() if hasattr(row, "_asdict") else vars(row))
        return rows
    if isinstance(frame, (list, tuple)):
        return [dict(row) if isinstance(row, dict) else vars(row) for row in frame]
    return []


def _timestamp(value: Any) -> int | None:
    text = str(value or "").strip()
    if not text:
        return None
    for candidate in (text, text.replace("Z", "+00:00")):
        try:
            parsed = datetime.fromisoformat(candidate)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=ZoneInfo(CN_A_SHARE.timezone))
            return int(parsed.astimezone(timezone.utc).timestamp())
        except ValueError:
            continue
    for fmt in ("%Y%m%d", "%Y-%m-%d", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            parsed = datetime.strptime(text, fmt).replace(tzinfo=timezone.utc)
            return int(parsed.timestamp())
        except ValueError:
            continue
    return None


def _number(value: Any) -> float | None:
    try:
        return None if value is None else float(value)
    except (TypeError, ValueError):
        return None


class TushareMarketDataProvider:
    provider_id = TUSHARE_PROVIDER
    provider_label_zh = "Tushare"
    profile = CN_A_SHARE

    def __init__(self, token: str | None = None, client: Any = None):
        self.token = (token or os.environ.get("TUSHARE_TOKEN", "")).strip()
        self._client = client

    def _client_or_raise(self):
        if self._client is not None:
            return self._client
        if not self.token:
            raise MarketDataProviderError("Tushare token 未配置")
        try:
            import tushare as ts
        except ImportError as exc:
            raise MarketDataProviderError("Tushare SDK 未安装") from exc
        ts.set_token(self.token)
        self._client = ts.pro_api(self.token)
        return self._client

    def capabilities(self, market_id: str | None = None) -> dict[str, Any]:
        return {
            "catalog": True,
            "quote": True,
            "history": True,
            "streaming": False,
            "periods": tuple(_PERIODS),
            "market": self.profile.market_id,
        }

    def status(self, market_id: str | None = None, symbol: str | None = None) -> dict[str, Any]:
        if not self.token and self._client is None:
            return unavailable_status(self.provider_id, reason="not_configured", detail="TUSHARE_TOKEN 未配置")
        return {"status": "ready", "provider": self.provider_id, "mode": "historical"}

    def _call_pro_bar(self, client, **kwargs):
        method = getattr(client, "pro_bar", None)
        if callable(method):
            return method(**kwargs)
        raise MarketDataProviderError("Tushare client does not expose pro_bar")

    def fetch_window(self, symbol: str, timeframe: str, **kwargs: Any) -> dict:
        freq = _PERIODS.get(str(timeframe).strip())
        if not freq:
            raise MarketDataProviderError(f"Tushare 不支持周期：{timeframe}")
        client = self._client_or_raise()
        try:
            frame = self._call_pro_bar(
                client,
                ts_code=str(symbol).upper(),
                freq=freq,
                start_date=kwargs.get("start_date"),
                end_date=kwargs.get("end_date"),
                adj=kwargs.get("adj", "qfq"),
            )
        except Exception as exc:
            raise MarketDataProviderError(f"Tushare 行情获取失败：{type(exc).__name__}") from exc
        completed = []
        for row in _records(frame):
            stamp = _timestamp(row.get("trade_time") or row.get("trade_date"))
            values = {key: _number(row.get(key)) for key in ("open", "high", "low", "close", "vol", "amount")}
            if stamp is None or any(values[key] is None for key in ("open", "high", "low", "close")):
                continue
            completed.append({
                "provider": self.provider_id,
                "market": self.profile.market_id,
                "symbol": str(symbol).upper(),
                "period": timeframe,
                "time": stamp,
                "open": values["open"],
                "high": values["high"],
                "low": values["low"],
                "close": values["close"],
                "volume": values["vol"],
                "amount": values["amount"],
                "is_closed": True,
                "timestamp": stamp,
                "sequence": None,
                "revision": 0,
                "mode": "historical",
            })
        completed.sort(key=lambda item: item["time"])
        return {"completed": completed, "forming": None, "meta": {"mode": "historical", "source": self.provider_id}}

    def fetch_recent(self, symbol: str, timeframe: str, **kwargs: Any) -> dict:
        return self.fetch_window(symbol, timeframe, **kwargs)

    def quote(self, symbol: str) -> dict:
        raise MarketDataProviderError("Tushare 实时报价需要已授权的实时分钟接口")

    def list_securities(self, market_id: str, query: str = "", page: int = 1) -> list[dict]:
        client = self._client_or_raise()
        method = getattr(client, "query", None)
        if not callable(method):
            raise MarketDataProviderError("Tushare client does not expose stock_basic")
        frame = method("stock_basic", exchange="", list_status="L", fields="ts_code,name,exchange,list_status")
        rows = _records(frame)
        needle = str(query or "").strip().upper()
        return [row for row in rows if not needle or needle in str(row.get("ts_code", "")).upper() or needle in str(row.get("name", ""))]

    def subscribe(self, symbol: str, timeframe: str, callback):
        raise MarketDataProviderError("Tushare 当前未提供本网站可用的共享 WebSocket 订阅")

    def unsubscribe(self, symbol: str, timeframe: str):
        return {"status": "unsupported", "provider": self.provider_id}
