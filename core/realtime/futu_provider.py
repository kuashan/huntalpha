import threading
import time

from futu import CurKlineHandlerBase, KLType, OpenQuoteContext, RET_OK, SubType

from .contracts import NormalizedBar, market_for_symbol, optional_numeric, provider_time_to_timestamp
from .provider import REALTIME_PERIOD_SUBTYPES, RealtimeMarketProvider, RealtimeProviderError


def _period_for_subtype(value):
    return next((period for period, subtype in REALTIME_PERIOD_SUBTYPES.items() if subtype == value), None)


class FutuRealtimeProvider(RealtimeMarketProvider):
    provider_name = "futu-opend"

    def __init__(self, host="127.0.0.1", port=11111, context_factory=None):
        self.host = host
        self.port = port
        self.context_factory = context_factory or (lambda: OpenQuoteContext(host=host, port=port, ai_type=1))
        self._context = None
        self._handler = None
        self._lock = threading.RLock()
        self._callbacks = {}
        self._status = "unavailable"

    @property
    def status(self):
        return self._status

    def _ensure_context(self):
        if self._context is not None:
            return self._context
        try:
            self._context = self.context_factory()
            provider = self

            class Handler(CurKlineHandlerBase):
                def on_recv_rsp(self, rsp_pb):
                    ret, frame = super().on_recv_rsp(rsp_pb)
                    if ret != RET_OK:
                        provider._notify_error(str(frame))
                        return ret, frame
                    provider._handle_frame(frame)
                    return ret, frame

            self._handler = Handler()
            self._context.set_handler(self._handler)
            self._status = "live"
            return self._context
        except Exception as exc:
            self._status = "unavailable"
            self._context = None
            raise RealtimeProviderError(f"富途 OpenD 不可用：{exc}") from exc

    def _key(self, symbol, period):
        if period not in REALTIME_PERIOD_SUBTYPES:
            raise RealtimeProviderError(f"周期 {period} 不支持实时 K 线")
        return str(symbol).upper(), period

    def _handle_frame(self, frame):
        received_at = int(time.time())
        for row in frame.itertuples(index=False):
            symbol = str(getattr(row, "code", "")).upper()
            period = _period_for_subtype(getattr(row, "k_type", None))
            if not symbol or not period:
                continue
            market = market_for_symbol(symbol)
            event_time = provider_time_to_timestamp(getattr(row, "time_key", None), market)
            if event_time is None:
                continue
            bar = NormalizedBar(
                provider=self.provider_name,
                market=market or "unknown",
                symbol=symbol,
                period=period,
                time=event_time,
                open=optional_numeric(getattr(row, "open", None)),
                high=optional_numeric(getattr(row, "high", None)),
                low=optional_numeric(getattr(row, "low", None)),
                close=optional_numeric(getattr(row, "close", None)),
                volume=optional_numeric(getattr(row, "volume", None)),
                amount=optional_numeric(getattr(row, "turnover", None)),
                turnover_rate=optional_numeric(getattr(row, "turnover_rate", None)),
                is_closed=None,
                provider_timestamp=received_at,
                sequence=getattr(row, "time_key", None),
                mode="streaming",
            )
            with self._lock:
                callbacks = list(self._callbacks.get((symbol, period), set()))
            for callback in callbacks:
                callback(bar)

    def _notify_error(self, message):
        with self._lock:
            self._status = "reconnecting"
            subscriptions = [(key, list(callbacks)) for key, callbacks in self._callbacks.items()]
        for (symbol, period), callbacks in subscriptions:
            for callback in callbacks:
                callback({"status": "reconnecting", "error": message, "symbol": symbol, "period": period})

    def subscribe(self, symbol, period, callback):
        symbol, period = self._key(symbol, period)
        context = self._ensure_context()
        key = (symbol, period)
        with self._lock:
            first = not self._callbacks.get(key)
            self._callbacks.setdefault(key, set()).add(callback)
        if first:
            try:
                ret, message = context.subscribe(
                    [symbol], [getattr(SubType, REALTIME_PERIOD_SUBTYPES[period])],
                    is_first_push=True, subscribe_push=True,
                )
                if ret != RET_OK:
                    raise RealtimeProviderError(str(message))
            except Exception as exc:
                with self._lock:
                    self._callbacks.get(key, set()).discard(callback)
                self._status = "unavailable"
                raise RealtimeProviderError(f"富途 OpenD 订阅 {symbol}/{period} 失败：{exc}") from exc
        return {"provider": self.provider_name, "mode": "streaming", "period": period}

    def unsubscribe(self, symbol, period):
        symbol, period = self._key(symbol, period)
        with self._lock:
            self._callbacks.pop((symbol, period), None)
        if self._context is None:
            return
        try:
            self._context.unsubscribe([symbol], [getattr(SubType, REALTIME_PERIOD_SUBTYPES[period])])
        except Exception:
            # OpenD may reject an unsubscribe before its one-minute subscription
            # window; the process-owned context is still closed on shutdown.
            pass

    def latest_snapshot(self, symbol, period):
        symbol, period = self._key(symbol, period)
        context = self._ensure_context()
        ret, payload = context.get_cur_kline(
            symbol, 1, ktype=getattr(KLType, REALTIME_PERIOD_SUBTYPES[period]), autype="qfq"
        )
        if ret != RET_OK or payload is None or payload.empty:
            raise RealtimeProviderError(str(payload))
        row = payload.iloc[-1]
        return next(
            (bar for bar in [self._row_to_bar(row, period)] if bar is not None),
            None,
        )

    def health_check(self):
        with self._lock:
            context = self._context
            keys = list(self._callbacks)
        if context is None or not keys:
            return self._status
        try:
            ret, _ = context.get_global_state()
            if ret != RET_OK:
                raise RealtimeProviderError("OpenD health check failed")
            self._status = "live"
            return self._status
        except Exception as exc:
            self._status = "reconnecting"
            self._notify_error(str(exc))
            try:
                self.reconnect()
            except Exception as reconnect_error:
                self._status = "unavailable"
                self._notify_error(str(reconnect_error))
            return self._status

    def reconnect(self):
        with self._lock:
            old_context = self._context
            self._context = None
            keys = list(self._callbacks)
            self._status = "reconnecting"
        if old_context is not None:
            try:
                old_context.close()
            except Exception:
                pass
        context = self._ensure_context()
        for symbol, period in keys:
            ret, message = context.subscribe(
                [symbol], [getattr(SubType, REALTIME_PERIOD_SUBTYPES[period])],
                is_first_push=True, subscribe_push=True,
            )
            if ret != RET_OK:
                raise RealtimeProviderError(str(message))
            snapshot = self.latest_snapshot(symbol, period)
            if snapshot is not None:
                with self._lock:
                    callbacks = list(self._callbacks.get((symbol, period), set()))
                for callback in callbacks:
                    callback(snapshot)
        self._status = "live"
        return True

    def _row_to_bar(self, row, period):
        symbol = str(row.get("code", "")).upper()
        market = market_for_symbol(symbol)
        event_time = provider_time_to_timestamp(row.get("time_key"), market)
        if event_time is None:
            return None
        return NormalizedBar(
            provider=self.provider_name,
            market=market or "unknown",
            symbol=symbol,
            period=period,
            time=event_time,
            open=optional_numeric(row.get("open")),
            high=optional_numeric(row.get("high")),
            low=optional_numeric(row.get("low")),
            close=optional_numeric(row.get("close")),
            volume=optional_numeric(row.get("volume")),
            amount=optional_numeric(row.get("turnover")),
            turnover_rate=optional_numeric(row.get("turnover_rate")),
            is_closed=None,
            provider_timestamp=int(time.time()),
            sequence=row.get("time_key"),
            mode="streaming",
        )

    def close(self):
        with self._lock:
            context, self._context = self._context, None
            self._callbacks.clear()
            self._status = "unavailable"
        if context is not None:
            context.close()
