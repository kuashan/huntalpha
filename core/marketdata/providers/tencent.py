from __future__ import annotations

"""腾讯财经公开行情 Provider。

该 Provider 不需要账号或 Token，作为 A 股/港股公开行情的完整窗口备用源，
并为美股提供公开报价补充。接口可能限流或变更，失败时由 Router 选择下一个
Provider；不会把不同供应商的 K 线拼接在一起。
"""

import json
import re
from datetime import datetime, timezone
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from ..profiles import CN_A_SHARE, HK_EQUITY, US_EQUITY, MarketProfile
from .base import MarketDataProviderError


TENCENT_PROVIDER = "tencent-public"
_PERIOD_KEYS = {"日线": "qfqday", "周线": "qfqweek", "月线": "qfqmonth"}


def tencent_symbol_for(symbol: str) -> str:
    normalized = str(symbol or "").strip().upper()
    prefix, separator, body = normalized.partition(".")
    if not separator:
        return normalized.lower()
    if prefix not in {"SH", "SSE", "SZ", "SZSE", "HK", "US"} and body in {"SH", "SSE", "SZ", "SZSE", "HK", "US"}:
        prefix, body = body, prefix
    if prefix in {"SH", "SSE"}:
        return f"sh{body}"
    if prefix in {"SZ", "SZSE"}:
        return f"sz{body}"
    if prefix == "HK":
        return f"hk{body.zfill(5)}"
    if prefix == "US":
        return f"us{body}"
    return normalized.lower()


def _number(value):
    try:
        return None if value in (None, "") else float(value)
    except (TypeError, ValueError):
        return None


def _time_to_timestamp(value, market: MarketProfile):
    text = str(value or "").strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y/%m/%d %H:%M:%S", "%Y%m%d%H%M%S", "%Y-%m-%d"):
        try:
            parsed = datetime.strptime(text, fmt)
            parsed = parsed.replace(tzinfo=ZoneInfo(market.timezone))
            return int(parsed.astimezone(timezone.utc).timestamp())
        except ValueError:
            continue
    return None


class TencentPublicMarketDataProvider:
    provider_id = TENCENT_PROVIDER
    provider_label_zh = "腾讯财经公开行情"

    def __init__(self, market: MarketProfile, *, timeout: int = 15, minimum_completed_bars: int = 120):
        self.profile = market
        self.timeout = timeout
        self.minimum_completed_bars = minimum_completed_bars

    def capabilities(self, market_id=None):
        return {"catalog": False, "quote": True, "history": True, "streaming": False, "polling": True, "public": True, "market": self.profile.market_id}

    def status(self, market_id=None, symbol=None):
        return {"status": "ready", "provider": self.provider_id, "mode": "public", "data_status": "delayed"}

    def _request_json(self, symbol: str, timeframe: str):
        provider_symbol = tencent_symbol_for(symbol)
        url = f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={quote(provider_symbol)},day,,,320,qfq"
        request = Request(url, headers={"User-Agent": "Mozilla/5.0 (HuntAlpha public market data)", "Accept": "application/json,text/plain,*/*"})
        try:
            with urlopen(request, timeout=self.timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except (HTTPError, URLError, TimeoutError, OSError, ValueError) as exc:
            raise MarketDataProviderError(f"腾讯财经请求失败：{type(exc).__name__}") from exc

    def _request_text(self, symbol: str):
        url = f"https://qt.gtimg.cn/q={quote(tencent_symbol_for(symbol))}"
        request = Request(url, headers={"User-Agent": "Mozilla/5.0 (HuntAlpha public market data)"})
        try:
            with urlopen(request, timeout=self.timeout) as response:
                return response.read().decode("gb18030", errors="replace")
        except (HTTPError, URLError, TimeoutError, OSError) as exc:
            raise MarketDataProviderError(f"腾讯报价请求失败：{type(exc).__name__}") from exc

    def fetch_window(self, symbol: str, timeframe: str, **kwargs):
        key = _PERIOD_KEYS.get(timeframe)
        if key is None:
            raise MarketDataProviderError(f"腾讯公开行情暂不支持周期：{timeframe}")
        payload = self._request_json(symbol, timeframe)
        data = payload.get("data") if isinstance(payload, dict) else None
        item = data.get(tencent_symbol_for(symbol)) if isinstance(data, dict) else None
        rows = item.get(key) if isinstance(item, dict) else None
        if not isinstance(rows, list):
            raise MarketDataProviderError("腾讯财经未返回完整历史窗口")
        completed = []
        for row in rows:
            if not isinstance(row, list) or len(row) < 6:
                continue
            stamp = _time_to_timestamp(row[0], self.profile)
            values = [_number(value) for value in row[1:6]]
            if stamp is None or any(value is None for value in values[:4]):
                continue
            completed.append({
                "time": stamp, "open": values[0], "close": values[1], "high": values[2], "low": values[3],
                "volume": values[4], "amount": None, "timestamp": stamp, "is_closed": True,
                "provider": self.provider_id, "market": self.profile.market_id, "symbol": str(symbol).upper(),
                "period": timeframe, "sequence": None, "revision": 0, "mode": "historical",
            })
        completed.sort(key=lambda item: item["time"])
        minimum = int(kwargs.get("minimum_completed_bars", self.minimum_completed_bars))
        if len(completed) < minimum:
            raise MarketDataProviderError(f"腾讯公开行情已完成 K 线不足 {minimum} 根")
        return {
            "completed": completed,
            "forming": None,
            "meta": {"provider": self.provider_id, "provider_label": self.provider_label_zh, "source": "network", "mode": "historical", "data_status": "delayed", "delay_seconds": None, "has_forming_bar": False},
        }

    def fetch_recent(self, symbol, timeframe, **kwargs):
        return self.fetch_window(symbol, timeframe, **kwargs)

    def quote(self, symbol: str):
        text = self._request_text(symbol)
        match = re.search(r"v_[^=]+=\"(.*?)\";", text, re.S)
        if not match:
            raise MarketDataProviderError("腾讯未返回真实报价")
        fields = match.group(1).split("~")
        price = _number(fields[3] if len(fields) > 3 else None)
        previous = _number(fields[4] if len(fields) > 4 else None)
        if price is None:
            raise MarketDataProviderError("腾讯报价缺少最新价")
        timestamp_index = next((index for index, value in enumerate(fields[10:], start=10) if re.fullmatch(r"\d{8}(?:\d{6})?|\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}", value or "")), None)
        updated_at = fields[timestamp_index] if timestamp_index is not None else None
        high = _number(fields[timestamp_index + 3]) if timestamp_index is not None and len(fields) > timestamp_index + 3 else None
        low = _number(fields[timestamp_index + 4]) if timestamp_index is not None and len(fields) > timestamp_index + 4 else None
        change = ((price - previous) / previous * 100) if previous else None
        return {
            "code": str(symbol).upper(), "price": price, "change": round(change, 3) if change is not None else None,
            "previous_close": previous, "open": _number(fields[5] if len(fields) > 5 else None),
            "high": high, "low": low, "volume": _number(fields[6] if len(fields) > 6 else None),
            "amount": None, "updated_at": updated_at, "source": self.provider_id, "status": "ready",
            "data_status": "delayed", "delay_seconds": None,
        }

    def list_securities(self, market_id, query="", page=1):
        raise MarketDataProviderError("腾讯公开行情不提供完整证券目录", status="unavailable")

    def subscribe(self, symbol, timeframe, callback):
        raise MarketDataProviderError("腾讯公开行情通过统一轮询实时 Provider 更新", status="unavailable")

    def unsubscribe(self, symbol, timeframe):
        return {"status": "unsupported", "provider": self.provider_id}
