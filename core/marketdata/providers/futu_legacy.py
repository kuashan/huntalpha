from __future__ import annotations

from datetime import datetime, timedelta, timezone
import os
import socket

from futu import AuType, KLType, OpenQuoteContext, RET_OK

from ..profiles import CN_A_SHARE, HK_EQUITY, US_EQUITY
from .base import MarketDataProviderError


_PERIODS = {"1分": KLType.K_1M, "5分": KLType.K_5M, "15分": KLType.K_15M, "30分": KLType.K_30M, "60分": KLType.K_60M, "2小时": KLType.K_120M, "4小时": KLType.K_240M, "日线": KLType.K_DAY, "周线": KLType.K_WEEK, "月线": KLType.K_MON}
_LOOKBACK_DAYS = {"1分": 14, "5分": 45, "15分": 90, "30分": 180, "60分": 365, "2小时": 730, "4小时": 1460, "日线": 1825, "周线": 7300, "月线": 14600}


def _number(value):
    try:
        number = float(value)
        return number if number == number and abs(number) != float("inf") else None
    except (TypeError, ValueError):
        return None


def _profile_market(profile):
    return {CN_A_SHARE.market_id: "cn", HK_EQUITY.market_id: "hk", US_EQUITY.market_id: "us"}[profile.market_id]


class FutuLegacyMarketDataProvider:
    """Compatibility adapter retained outside the default SLTD-aligned route."""

    # Keep the historical id for the compatibility seam so old clients and
    # regression fixtures remain readable.  The provider is never registered
    # in the default router.
    provider_id = "futu-opend"
    provider_label_zh = "Futu OpenD（兼容）"

    def __init__(self, profile, context_factory=None):
        self.profile = profile
        self.host = os.environ.get("FUTU_OPEND_HOST", "127.0.0.1")
        self.port = int(os.environ.get("FUTU_OPEND_PORT", "11111"))
        self._injected_context = context_factory is not None
        self.context_factory = context_factory or (lambda: OpenQuoteContext(host=self.host, port=self.port, ai_type=1))

    def _context(self):
        # An injected context is used only by explicit compatibility callers
        # and tests.  The default path still performs a bounded health probe.
        if self._injected_context:
            return self.context_factory()
        try:
            with socket.create_connection((self.host, self.port), timeout=1):
                pass
        except OSError as exc:
            raise MarketDataProviderError("Futu OpenD 不可用") from exc
        return self.context_factory()

    def open_context(self):
        return self._context()

    def capabilities(self, market_id=None):
        return {"catalog": True, "quote": True, "history": True, "streaming": True, "legacy": True, "market": self.profile.market_id}

    def status(self, market_id=None, symbol=None):
        try:
            with socket.create_connection((self.host, self.port), timeout=0.2):
                return {"status": "ready", "provider": self.provider_id, "mode": "legacy"}
        except OSError:
            return {"status": "unavailable", "provider": self.provider_id, "mode": "unavailable"}

    def quote(self, symbol):
        client = self._context()
        try:
            ret, frame = client.get_market_snapshot([str(symbol).upper()])
            if ret != RET_OK or frame.empty:
                raise MarketDataProviderError("Futu OpenD 未返回真实报价")
            row = frame.iloc[0]
            price = _number(row.get("last_price"))
            if price is None:
                raise MarketDataProviderError("Futu OpenD 报价缺少有效最新价")
            previous = _number(row.get("prev_close_price"))
            return {"code": row.get("code", str(symbol).upper()), "name": row.get("name", ""), "price": price, "change": round((price - previous) / previous * 100, 3) if previous else None, "open": _number(row.get("open_price")), "high": _number(row.get("high_price")), "low": _number(row.get("low_price")), "updated_at": row.get("update_time"), "source": self.provider_id, "status": "ready"}
        finally:
            client.close()

    def fetch_window(self, symbol, timeframe, **kwargs):
        period = _PERIODS.get(timeframe)
        if period is None:
            raise MarketDataProviderError(f"Futu OpenD 不支持周期：{timeframe}")
        client = self._context()
        try:
            before = kwargs.get("before")
            market_tz = timezone.utc
            end = datetime.fromtimestamp(int(before), tz=market_tz) if before else datetime.now(timezone.utc)
            start = end - timedelta(days=_LOOKBACK_DAYS.get(timeframe, 1825))
            ret, frame, _ = client.request_history_kline(str(symbol).upper(), start=start.strftime("%Y-%m-%d"), end=end.strftime("%Y-%m-%d"), ktype=period, autype=AuType.QFQ, max_count=None)
            if ret != RET_OK or frame.empty:
                raise MarketDataProviderError("Futu OpenD 未返回历史 K 线")
            completed = []
            for row in frame.itertuples(index=False):
                stamp = str(getattr(row, "time_key", ""))
                try:
                    parsed = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
                    if parsed.tzinfo is None:
                        parsed = parsed.replace(tzinfo=market_tz)
                    event_time = int(parsed.astimezone(timezone.utc).timestamp())
                except (TypeError, ValueError):
                    continue
                if before and event_time >= int(before):
                    continue
                completed.append({"provider": self.provider_id, "market": self.profile.market_id, "symbol": str(symbol).upper(), "period": timeframe, "time": event_time, "open": _number(getattr(row, "open", None)), "high": _number(getattr(row, "high", None)), "low": _number(getattr(row, "low", None)), "close": _number(getattr(row, "close", None)), "volume": _number(getattr(row, "volume", None)), "amount": _number(getattr(row, "turnover", None)), "is_closed": True, "timestamp": event_time, "sequence": None, "revision": 0, "mode": "historical"})
            completed = [row for row in completed if all(row[key] is not None for key in ("open", "high", "low", "close"))]
            completed.sort(key=lambda row: row["time"])
            return {"completed": completed[-int(kwargs.get("limit", 1000)):], "forming": None, "meta": {"mode": "historical", "source": self.provider_id, "adjustment": "前复权"}}
        finally:
            client.close()

    def fetch_recent(self, symbol, timeframe, **kwargs):
        return self.fetch_window(symbol, timeframe, **kwargs)

    def list_securities(self, market_id, query="", page=1):
        raise MarketDataProviderError("Futu legacy catalog is only available through the explicit catalog adapter")

    def subscribe(self, symbol, timeframe, callback):
        raise MarketDataProviderError("Futu legacy realtime subscription is managed by the shared realtime adapter")

    def unsubscribe(self, symbol, timeframe):
        return {"status": "unsupported", "provider": self.provider_id}
