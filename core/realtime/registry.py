import queue
import threading
import time
from dataclasses import dataclass, field

from .contracts import NormalizedBar
from .contracts import market_for_symbol
from .provider import RealtimeProviderError
from .state import RealtimeStateStore


@dataclass(eq=False)
class RealtimeConsumer:
    key: tuple
    events: queue.Queue = field(default_factory=queue.Queue)
    closed: bool = False

    def get(self, timeout=None):
        return self.events.get(timeout=timeout)

    def close(self):
        self.closed = True


class RealtimeRegistry:
    def __init__(self, provider, state_store=None, grace_seconds=20, health_interval_seconds=5.0):
        self.provider = provider
        self.provider_name = str(provider.provider_name)
        self.state_store = state_store or RealtimeStateStore()
        self.grace_seconds = grace_seconds
        self._entries = {}
        self._lock = threading.RLock()
        self.health_interval_seconds = max(0.1, float(health_interval_seconds))
        self._health_lock = threading.Lock()
        self._health_inflight = False
        self._last_health_check = 0.0

    def _key(self, symbol, period):
        normalized = str(symbol).upper()
        return (self.provider_name_for(symbol), market_for_symbol(normalized) or "unknown", normalized, period)

    def provider_name_for(self, symbol):
        resolver = getattr(self.provider, "provider_name_for", None)
        return resolver(symbol) if resolver else self.provider_name

    def key_for(self, symbol, period):
        return self._key(symbol, period)

    def _publish(self, key, payload):
        with self._lock:
            entry = self._entries.get(key)
            consumers = list(entry["consumers"]) if entry else []
        for consumer in consumers:
            if not consumer.closed:
                consumer.events.put(payload)

    def _provider_event(self, key, event):
        if isinstance(event, NormalizedBar):
            state, merge = self.state_store.apply_bar(
                key, event, status="live", mode=event.mode, source=event.provider,
            )
            if merge.accepted:
                self._publish(key, {"type": "bar" if merge.relation != "initial" else "snapshot", **state.to_dict()})
            return
        status = event.get("status", "unavailable")
        state = self.state_store.set_status(
            key, status, mode=event.get("mode", "streaming"), source=event.get("source") or key[0], error=event.get("error"),
        )
        self._publish(key, {"type": "status", **state.to_dict()})

    def subscribe(self, symbol, period):
        key = self._key(symbol, period)
        consumer = RealtimeConsumer(key)
        with self._lock:
            entry = self._entries.get(key)
            if entry and entry.get("timer"):
                entry["timer"].cancel()
                entry["timer"] = None
            if entry is None:
                self._entries[key] = {"consumers": set(), "timer": None, "subscribed": False}
                first = True
            else:
                first = False
            self._entries[key]["consumers"].add(consumer)
            if not first:
                subscribed = bool(self._entries[key]["subscribed"])
            else:
                subscribed = False
                self.state_store.set_status(key, "connecting", source=key[0])
                try:
                    self.provider.subscribe(symbol, period, lambda event: self._provider_event(key, event))
                except Exception as exc:
                    failed = self._entries.pop(key, None)
                    if failed and failed.get("timer"):
                        failed["timer"].cancel()
                    if failed:
                        failed["consumers"].clear()
                    consumer.close()
                    try:
                        self.provider.unsubscribe(symbol, period)
                    except Exception:
                        pass
                    self.state_store.set_status(key, "unavailable", source=key[0], error=str(exc))
                    raise RealtimeProviderError(str(exc)) from exc
                self._entries[key]["subscribed"] = True
                subscribed = True

        if first and subscribed:
            try:
                bar = self.provider.latest_snapshot(symbol, period)
            except Exception as exc:
                self.state_store.set_status(key, "reconnecting", source=key[0], error=str(exc))
            else:
                if bar is not None:
                    self._provider_event(key, bar)

        state = self.state_store.get(key)
        if state is None or state.status == "connecting":
            state = self.state_store.set_status(key, "live", mode="streaming", source=key[0])
        consumer.events.put({"type": "status", **state.to_dict()})
        latest = self.state_store.get(key)
        if latest and latest.current_bar:
            consumer.events.put({"type": "snapshot", **latest.to_dict()})
        return consumer

    def unsubscribe(self, consumer):
        if consumer is None or consumer.closed:
            return
        consumer.close()
        key = consumer.key
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                return
            entry["consumers"].discard(consumer)
            if entry["consumers"]:
                return
            timer = threading.Timer(self.grace_seconds, self._remove_entry, args=(key,))
            timer.daemon = True
            entry["timer"] = timer
            timer.start()

    def _remove_entry(self, key):
        with self._lock:
            entry = self._entries.get(key)
            if entry is None or entry["consumers"]:
                return
            self._entries.pop(key, None)
        try:
            if entry.get("subscribed"):
                self.provider.unsubscribe(key[2], key[3])
        finally:
            self.state_store.set_status(key, "unavailable", source=key[0])

    def stats(self, key=None):
        with self._lock:
            if key is not None:
                entry = self._entries.get(key)
                return {
                    "consumer_count": len(entry["consumers"]) if entry else 0,
                    "provider_subscription_count": 1 if entry and entry.get("subscribed") else 0,
                }
            return {
                "active_keys": len(self._entries),
                "consumer_count": sum(len(entry["consumers"]) for entry in self._entries.values()),
                "provider_subscription_count": sum(1 for entry in self._entries.values() if entry.get("subscribed")),
            }

    def close(self):
        with self._lock:
            entries = list(self._entries.items())
            self._entries.clear()
        for key, entry in entries:
            if entry.get("timer"):
                entry["timer"].cancel()
            if entry.get("subscribed"):
                try:
                    self.provider.unsubscribe(key[2], key[3])
                except Exception:
                    pass
        self.provider.close()

    def _provider_status(self):
        try:
            return self.provider.status
        except AttributeError:
            return "live"

    def _has_active_consumers(self):
        with self._lock:
            return any(entry["consumers"] for entry in self._entries.values())

    def health_check(self):
        if not self._has_active_consumers():
            return self._provider_status()
        check = getattr(self.provider, "health_check", None)
        if check is None:
            return "live"
        now = time.monotonic()
        with self._health_lock:
            if self._health_inflight or now - self._last_health_check < self.health_interval_seconds:
                return self._provider_status()
            self._health_inflight = True
            self._last_health_check = now
        try:
            return check()
        except Exception:
            return self._provider_status()
        finally:
            with self._health_lock:
                self._health_inflight = False


_default_registry = None
_default_lock = threading.Lock()


def create_default_realtime_registry(**kwargs):
    """Application composition point for the currently selected provider."""
    from ..crypto_provider import CoinbaseRealtimeProvider
    from .futu_provider import FutuRealtimeProvider
    from .router import MarketDataProviderRouter

    return RealtimeRegistry(
        provider=MarketDataProviderRouter(FutuRealtimeProvider(), CoinbaseRealtimeProvider()),
        **kwargs,
    )


def get_realtime_registry():
    global _default_registry
    with _default_lock:
        if _default_registry is None:
            _default_registry = create_default_realtime_registry()
        return _default_registry
