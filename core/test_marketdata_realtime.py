from unittest import TestCase

from .realtime.contracts import NormalizedBar
from .realtime.registry import RealtimeRegistry
from .realtime.state import RealtimeStateStore


class FakeRealtimeProvider:
    provider_name = "provider-a"

    def __init__(self):
        self.callbacks = {}

    def subscribe(self, symbol, period, callback):
        self.callbacks[(symbol, period)] = callback

    def unsubscribe(self, symbol, period):
        self.callbacks.pop((symbol, period), None)

    def latest_snapshot(self, symbol, period):
        return None

    def close(self):
        self.callbacks.clear()


class UnifiedRealtimeBoundaryTests(TestCase):
    def test_registry_identity_contains_provider_market_symbol_and_period(self):
        registry = RealtimeRegistry(FakeRealtimeProvider(), state_store=RealtimeStateStore(), grace_seconds=0)
        consumer = registry.subscribe("SH.600519", "1分")
        self.assertEqual(consumer.key, ("provider-a", "cn", "SH.600519", "1分"))
        registry.unsubscribe(consumer)

    def test_state_payload_keeps_symbol_and_exposes_market(self):
        registry = RealtimeRegistry(FakeRealtimeProvider(), state_store=RealtimeStateStore(), grace_seconds=0)
        consumer = registry.subscribe("CC.BTC-USD", "1分")
        callback = registry.provider.callbacks[("CC.BTC-USD", "1分")]
        callback(NormalizedBar(
            provider="provider-a", market="crypto", symbol="CC.BTC-USD", period="1分", time=1,
            open=1, high=2, low=1, close=2, volume=3,
        ))
        events = [consumer.get(timeout=0.2) for _ in range(2)]
        snapshot = next(event for event in events if event["type"] == "snapshot")
        self.assertEqual(snapshot["symbol"], "CC.BTC-USD")
        self.assertEqual(snapshot["market"], "crypto")
        registry.unsubscribe(consumer)
