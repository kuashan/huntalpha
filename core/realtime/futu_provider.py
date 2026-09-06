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
        self._connection_generation = 0
        self._ready_generation = None
        self._generation_subscriptions = set()
        self._reconnect_lock = threading.Lock()

    @property
    def connection_generation(self):
        with self._lock:
            return self._connection_generation

    @property
    def status(self):
        with self._lock:
            return self._status

    def _build_context(self, generation):
        context = self.context_factory()
        provider = self

        class Handler(CurKlineHandlerBase):
            def on_recv_rsp(self, rsp_pb):
                ret, frame = super().on_recv_rsp(rsp_pb)
                provider._handle_response(generation, ret, frame)
                return ret, frame

        handler = Handler()
        try:
            context.set_handler(handler)
        except Exception:
            try:
                context.close()
            except Exception:
                pass
            raise
        return context, handler

    def _ensure_context(self):
        with self._lock:
            if self._context is not None:
                return self._context
            self._connection_generation += 1
            generation = self._connection_generation
        try:
            context, handler = self._build_context(generation)
            with self._lock:
                if generation != self._connection_generation:
                    context.close()
                    raise RealtimeProviderError("富途 OpenD 连接代际已过期")
                self._context = context
                self._handler = handler
                self._ready_generation = generation
                self._generation_subscriptions = set()
                self._status = "live"
            return context
        except Exception as exc:
            with self._lock:
                if generation == self._connection_generation:
                    self._status = "unavailable"
                    self._context = None
                    self._handler = None
                    self._ready_generation = None
                    self._generation_subscriptions = set()
            raise RealtimeProviderError(f"富途 OpenD 不可用：{exc}") from exc

    def _key(self, symbol, period):
        if period not in REALTIME_PERIOD_SUBTYPES:
            raise RealtimeProviderError(f"周期 {period} 不支持实时 K 线")
        return str(symbol).upper(), period

    def _handle_response(self, generation, ret, frame):
        with self._lock:
            if generation != self._connection_generation or generation != self._ready_generation:
                return
        if ret != RET_OK:
            self._notify_error(str(frame), generation=generation)
            return
        self._handle_frame(frame, generation=generation)

    def _handle_frame(self, frame, generation=None):
        with self._lock:
            if generation is not None and (
                generation != self._connection_generation or generation != self._ready_generation
            ):
                return
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
                sequence=None,
                mode="streaming",
                event_kind="live",
            )
            with self._lock:
                if generation is not None and generation != self._connection_generation:
                    return
                callbacks = list(self._callbacks.get((symbol, period), set()))
            for callback in callbacks:
                callback(bar)

    def _notify_status(self, status, message, generation=None):
        with self._lock:
            if generation is not None and generation != self._connection_generation:
                return
            self._status = status
            subscriptions = [(key, list(callbacks)) for key, callbacks in self._callbacks.items()]
        for (symbol, period), callbacks in subscriptions:
            for callback in callbacks:
                with self._lock:
                    if generation is not None and generation != self._connection_generation:
                        return
                callback({"status": status, "error": message, "symbol": symbol, "period": period})

    def _notify_error(self, message, status="reconnecting", generation=None):
        self._notify_status(status, message, generation=generation)

    def subscribe(self, symbol, period, callback):
        with self._reconnect_lock:
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
                    with self._lock:
                        if context is self._context and self._ready_generation == self._connection_generation:
                            self._generation_subscriptions.add(key)
                except Exception as exc:
                    with self._lock:
                        self._callbacks.get(key, set()).discard(callback)
                        if not self._callbacks.get(key):
                            self._callbacks.pop(key, None)
                        self._generation_subscriptions.discard(key)
                        self._status = "unavailable"
                    raise RealtimeProviderError(f"富途 OpenD 订阅 {symbol}/{period} 失败：{exc}") from exc
            return {"provider": self.provider_name, "mode": "streaming", "period": period}

    def unsubscribe(self, symbol, period):
        with self._reconnect_lock:
            symbol, period = self._key(symbol, period)
            with self._lock:
                self._callbacks.pop((symbol, period), None)
                self._generation_subscriptions.discard((symbol, period))
                context = self._context
            if context is None:
                return
            try:
                context.unsubscribe([symbol], [getattr(SubType, REALTIME_PERIOD_SUBTYPES[period])])
            except Exception:
                # OpenD may reject an unsubscribe before its one-minute subscription
                # window; the process-owned context is still closed on shutdown.
                pass

    def _latest_snapshot_from_context(self, context, symbol, period):
        ret, payload = context.get_cur_kline(
            symbol, 1, ktype=getattr(KLType, REALTIME_PERIOD_SUBTYPES[period]), autype="qfq"
        )
        if ret != RET_OK or payload is None or payload.empty:
            raise RealtimeProviderError(str(payload))
        row = payload.iloc[-1]
        return self._row_to_bar(row, period)

    def _reconnect_snapshot(self, context, symbol, period):
        return self._latest_snapshot_from_context(context, symbol, period)

    def latest_snapshot(self, symbol, period):
        with self._reconnect_lock:
            symbol, period = self._key(symbol, period)
            context = self._ensure_context()
            return self._latest_snapshot_from_context(context, symbol, period)

    def health_check(self):
        with self._lock:
            context = self._context
            keys = list(self._callbacks)
            generation = self._connection_generation
            ready_generation = self._ready_generation
            generation_subscriptions = set(self._generation_subscriptions)
            status = self._status
        if not keys:
            return status
        if context is None or ready_generation != generation or set(keys) != generation_subscriptions:
            self._notify_error("OpenD context unavailable", status="reconnecting", generation=generation)
            try:
                self.reconnect()
            except Exception as reconnect_error:
                self._notify_error(str(reconnect_error), status="unavailable", generation=self.connection_generation)
            return self.status
        try:
            ret, _ = context.get_global_state()
            if ret != RET_OK:
                raise RealtimeProviderError("OpenD health check failed")
            with self._lock:
                if generation != self._connection_generation or context is not self._context:
                    return self._status
                complete = (
                    self._ready_generation == generation
                    and set(self._callbacks) == self._generation_subscriptions
                )
                if complete:
                    self._status = "live"
                    return self._status
            self._notify_error("OpenD subscriptions incomplete", status="reconnecting", generation=generation)
            try:
                self.reconnect()
            except Exception as reconnect_error:
                self._notify_error(str(reconnect_error), status="unavailable", generation=self.connection_generation)
            return self._status
        except Exception as exc:
            with self._lock:
                if generation != self._connection_generation or context is not self._context:
                    return self._status
            self._notify_error(str(exc), status="reconnecting", generation=generation)
            try:
                self.reconnect()
            except Exception as reconnect_error:
                self._notify_error(str(reconnect_error), status="unavailable", generation=self.connection_generation)
            return self._status

    def reconnect(self):
        with self._reconnect_lock:
            with self._lock:
                old_context = self._context
                self._context = None
                self._handler = None
                self._ready_generation = None
                # Invalidate callbacks from the old OpenD context before closing
                # it.  The candidate context is not exposed until all active
                # subscriptions and authoritative snapshots have succeeded.
                self._connection_generation += 1
                generation = self._connection_generation
                keys = list(self._callbacks)
                self._generation_subscriptions = set()
                self._status = "reconnecting"
            if old_context is not None:
                try:
                    old_context.close()
                except Exception:
                    pass
            candidate = None
            try:
                candidate, candidate_handler = self._build_context(generation)
                snapshots = []
                for symbol, period in keys:
                    ret, message = candidate.subscribe(
                        [symbol], [getattr(SubType, REALTIME_PERIOD_SUBTYPES[period])],
                        is_first_push=True, subscribe_push=True,
                    )
                    if ret != RET_OK:
                        raise RealtimeProviderError(str(message))
                for symbol, period in keys:
                    snapshot = self._reconnect_snapshot(candidate, symbol, period)
                    if snapshot is None:
                        raise RealtimeProviderError(f"富途 OpenD 快照 {symbol}/{period} 为空")
                    snapshots.append(((symbol, period), snapshot))

                with self._lock:
                    if generation != self._connection_generation:
                        raise RealtimeProviderError("富途 OpenD 连接代际已过期")
                    current_keys = set(self._callbacks)
                    captured_keys = set(keys)
                    added_keys = current_keys - captured_keys
                    if added_keys:
                        raise RealtimeProviderError("重连期间出现新的实时订阅")
                    for symbol, period in captured_keys - current_keys:
                        try:
                            candidate.unsubscribe(
                                [symbol], [getattr(SubType, REALTIME_PERIOD_SUBTYPES[period])]
                            )
                        except Exception:
                            pass
                    self._context = candidate
                    self._handler = candidate_handler
                    self._ready_generation = generation
                    self._generation_subscriptions = set(current_keys)
                    self._status = "live"
                    candidate = None

                for (symbol, period), snapshot in snapshots:
                    with self._lock:
                        callbacks = list(self._callbacks.get((symbol, period), set()))
                    for callback in callbacks:
                        callback(snapshot)
                self._notify_status("live", None, generation=generation)
                return True
            except Exception as exc:
                if candidate is not None:
                    try:
                        candidate.close()
                    except Exception:
                        pass
                with self._lock:
                    if generation == self._connection_generation:
                        self._context = None
                        self._handler = None
                        self._ready_generation = None
                        self._generation_subscriptions = set()
                        self._status = "unavailable"
                if isinstance(exc, RealtimeProviderError):
                    raise
                raise RealtimeProviderError(f"富途 OpenD 重连失败：{exc}") from exc

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
            sequence=None,
            mode="streaming",
            event_kind="reconcile",
        )

    def close(self):
        with self._lock:
            self._connection_generation += 1
            context, self._context = self._context, None
            self._handler = None
            self._ready_generation = None
            self._generation_subscriptions = set()
            self._callbacks.clear()
            self._status = "unavailable"
        if context is not None:
            context.close()
