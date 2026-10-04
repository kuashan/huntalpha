import os
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest import TestCase, mock
from pathlib import Path

from .marketdata.service import build_realtime_provider
from .marketdata.service import MarketDataService
from .realtime.longbridge_provider import LongbridgeRealtimeProvider
from .realtime.contracts import NormalizedBar
from .realtime.registry import RealtimeRegistry
from .realtime.state import RealtimeStateStore
from .realtime.provider import RealtimeProviderError
from .realtime.tushare_provider import TushareRealtimeProvider


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
    def test_default_registry_composition_is_delegated_to_marketdata_service(self):
        source = Path(__file__).with_name("realtime") / "registry.py"
        text = source.read_text(encoding="utf-8")
        self.assertNotIn("from .futu_provider import", text)
        self.assertIn("marketdata.service", text)

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

    def test_default_realtime_router_is_provider_neutral(self):
        router = build_realtime_provider()
        self.assertEqual(router.provider_name_for("SH.600519"), "tushare")
        self.assertEqual(router.provider_name_for("HK.00700"), "longbridge")
        self.assertEqual(router.provider_name_for("US.AAPL"), "longbridge")
        self.assertEqual(router.provider_name_for("CC.BTC-USD"), "coinbase")
        self.assertNotIn("futu-opend", router.provider_names)

    def test_index_status_does_not_open_opend_when_unconfigured(self):
        payload = MarketDataService().index_snapshot_response()
        self.assertEqual(payload["source"], "marketdata-router")
        self.assertNotIn("futu-opend", {item["source"] for group in payload["markets"] for item in group["items"]})

    def test_longbridge_stream_normalizes_forming_and_confirmed_candlesticks(self):
        class Context:
            def __init__(self):
                self.callback = None
                self.subscriptions = []

            def set_on_candlestick(self, callback):
                self.callback = callback

            def subscribe_candlesticks(self, symbol, period):
                self.subscriptions.append((symbol, period))
                return []

            def unsubscribe_candlesticks(self, symbol, period):
                return None

            def realtime_candlesticks(self, symbol, period, count):
                return []

            def close(self):
                return None

        context = Context()
        provider = LongbridgeRealtimeProvider(token="test-token", context=context)
        events = []
        provider.subscribe("HK.00700", "1分", events.append)
        context.callback("700.HK", SimpleNamespace(
            period=SimpleNamespace(name="Min_1"),
            is_confirmed=False,
            candlestick=SimpleNamespace(
                timestamp=datetime(2026, 10, 4, 1, 0, tzinfo=timezone.utc),
                open=10, high=11, low=9, close=10.5, volume=100, turnover=1050,
            ),
        ))
        self.assertEqual(context.subscriptions[0][0], "700.HK")
        self.assertEqual(events[-1].provider, "longbridge")
        self.assertEqual(events[-1].market, "hk")
        self.assertEqual(events[-1].symbol, "HK.00700")
        self.assertFalse(events[-1].is_closed)
        context.callback("700.HK", SimpleNamespace(
            period=SimpleNamespace(name="Min_1"),
            is_confirmed=True,
            candlestick=SimpleNamespace(
                timestamp=datetime(2026, 10, 4, 1, 1, tzinfo=timezone.utc),
                open=10.5, high=12, low=10, close=11.5, volume=200, turnover=2250,
            ),
        ))
        self.assertTrue(events[-1].is_closed)
        self.assertEqual(events[-1].sequence, 2)
        provider.close()

    def test_longbridge_without_credentials_is_not_configured(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            provider = LongbridgeRealtimeProvider()
        self.assertEqual(provider.status, "not_configured")
        with self.assertRaises(RealtimeProviderError) as raised:
            provider.subscribe("HK.00700", "1分", lambda event: None)
        self.assertEqual(raised.exception.status, "not_configured")

    def test_tushare_polling_emits_real_provider_contract(self):
        class Client:
            def realtime_quote(self, symbol, period):
                return {"ts_code": symbol, "trade_time": "2026-10-04 09:31:00", "open": 10, "high": 11, "low": 9, "close": 10.5, "vol": 100, "amount": 1050}

        provider = TushareRealtimeProvider(token="test-token", client=Client())
        events = []
        provider.subscribe("SH.600519", "1分", events.append)
        provider.poll_once()
        bar = next(event for event in events if isinstance(event, NormalizedBar))
        self.assertEqual(bar.provider, "tushare")
        self.assertEqual(bar.market, "cn")
        self.assertEqual(bar.mode, "polling")
        self.assertFalse(bar.is_closed)
        self.assertEqual(bar.close, 10.5)
        self.assertGreaterEqual(bar.sequence, 1)
        provider.close()
