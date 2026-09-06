import json
import queue
import threading
from dataclasses import dataclass, field

from .contracts import NormalizedBar
from .futu_provider import FutuRealtimeProvider
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
    def __init__(self, provider=None, state_store=None, grace_seconds=20):
        self.provider = provider or FutuRealtimeProvider()
        self.state_store = state_store or RealtimeStateStore()
        self.grace_seconds = grace_seconds
        self._entries = {}
        self._lock = threading.RLock()

    @staticmethod
    def _key(symbol, period):
        return ("futu-opend", str(symbol).upper(), period)

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
            key, status, mode=event.get("mode", "streaming"), source="futu-opend", error=event.get("error"),
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
                self._entries[key] = {"consumers": set(), "timer": None}
                first = True
            else:
                first = False
            self._entries[key]["consumers"].add(consumer)
        try:
            if first:
                self.state_store.set_status(key, "connecting", source="futu-opend")
                self.provider.subscribe(symbol, period, lambda event: self._provider_event(key, event))
            bar = self.provider.latest_snapshot(symbol, period)
            if bar is not None:
                self._provider_event(key, bar)
            state = self.state_store.set_status(key, "live", mode="streaming", source="futu-opend")
            consumer.events.put({"type": "status", **state.to_dict()})
            latest = self.state_store.get(key)
            if latest and latest.current_bar:
                consumer.events.put({"type": "snapshot", **latest.to_dict()})
            return consumer
        except Exception as exc:
            self.unsubscribe(consumer)
            raise RealtimeProviderError(str(exc)) from exc

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
            self.provider.unsubscribe(key[1], key[2])
        finally:
            self.state_store.set_status(key, "unavailable", source="futu-opend")

    def stats(self, key=None):
        with self._lock:
            if key is not None:
                entry = self._entries.get(key)
                return {"consumer_count": len(entry["consumers"]) if entry else 0, "provider_subscription_count": 1 if entry else 0}
            return {
                "active_keys": len(self._entries),
                "consumer_count": sum(len(entry["consumers"]) for entry in self._entries.values()),
                "provider_subscription_count": len(self._entries),
            }

    def close(self):
        with self._lock:
            entries = list(self._entries.values())
            self._entries.clear()
        for entry in entries:
            if entry.get("timer"):
                entry["timer"].cancel()
        self.provider.close()

    def health_check(self):
        check = getattr(self.provider, "health_check", None)
        return check() if check else "live"


_default_registry = None
_default_lock = threading.Lock()


def get_realtime_registry():
    global _default_registry
    with _default_lock:
        if _default_registry is None:
            _default_registry = RealtimeRegistry()
        return _default_registry
