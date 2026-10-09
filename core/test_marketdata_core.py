from types import SimpleNamespace
from unittest import TestCase

from .marketdata import (
    CN_A_SHARE,
    CRYPTO_24_7,
    HK_EQUITY,
    US_EQUITY,
    MarketDataFetch,
    MarketDataRouter,
    MarketDataCache,
    cache_key,
)


class FakeProvider:
    def __init__(self, provider_id, profile, payload=None, error=None):
        self.provider_id = provider_id
        self.provider_label_zh = provider_id
        self.profile = profile
        self.payload = payload if payload is not None else {"completed": [{"close": 1}], "forming": None}
        self.error = error
        self.calls = []

    def fetch_window(self, symbol, timeframe, **kwargs):
        self.calls.append((symbol, timeframe, dict(kwargs)))
        if self.error:
            raise self.error
        return self.payload

    def capabilities(self, market_id=None):
        return {"quote": True, "history": True}

    def status(self, market_id=None, symbol=None):
        return {"status": "live", "provider": self.provider_id}


class MarketDataCoreTests(TestCase):
    def test_profiles_keep_market_rules_independent_from_provider(self):
        self.assertEqual(CRYPTO_24_7.timezone, "UTC")
        self.assertTrue(CRYPTO_24_7.continuous)
        self.assertEqual(US_EQUITY.sessions, (("09:30", "16:00"),))
        self.assertEqual(CN_A_SHARE.sessions, (("09:30", "11:30"), ("13:00", "15:00")))
        self.assertEqual(HK_EQUITY.timezone, "Asia/Hong_Kong")
        self.assertFalse(HK_EQUITY.continuous)

    def test_cache_key_isolated_by_market_symbol_timeframe_and_provider(self):
        keys = {
            cache_key("CN_A_SHARE", "600519.SH", "1d", "TUSHARE"),
            cache_key("HK_EQUITY", "600519.SH", "1d", "TUSHARE"),
            cache_key("CN_A_SHARE", "600519.SH", "1h", "TUSHARE"),
            cache_key("CN_A_SHARE", "600519.SH", "1d", "LONGBRIDGE"),
        }
        self.assertEqual(len(keys), 4)

    def test_router_fails_over_by_refetching_the_complete_window(self):
        first = FakeProvider("P1", US_EQUITY, error=RuntimeError("provider down"))
        second = FakeProvider(
            "P2",
            US_EQUITY,
            payload={
                "completed": [{"time": 1}, {"time": 2}],
                "forming": {"time": 3},
                "meta": {"mode": "historical"},
            },
        )
        router = MarketDataRouter()
        router.register(first)
        router.register(second)

        result = router.fetch_window(
            "US_EQUITY",
            "AAPL.US",
            "1d",
            limit=300,
            start="2020-01-01",
        )

        self.assertIsInstance(result, MarketDataFetch)
        self.assertEqual(result.provider_id, "P2")
        self.assertEqual(result.completed, [{"time": 1}, {"time": 2}])
        self.assertEqual(result.forming, {"time": 3})
        self.assertEqual(first.calls, [("AAPL.US", "1d", {"limit": 300, "start": "2020-01-01"})])
        self.assertEqual(second.calls, first.calls)

    def test_router_does_not_use_provider_from_another_market(self):
        router = MarketDataRouter()
        router.register(FakeProvider("US", US_EQUITY))
        with self.assertRaisesRegex(RuntimeError, "没有可用行情供应商"):
            router.fetch_window("HK_EQUITY", "700.HK", "1d", limit=300)

    def test_provider_status_and_capabilities_are_exposed_without_sdk_fields(self):
        provider = FakeProvider("P1", US_EQUITY)
        router = MarketDataRouter()
        router.register(provider)
        self.assertEqual(router.provider_ids("US_EQUITY"), ("P1",))
        self.assertEqual(router.capabilities("US_EQUITY", "P1"), {"quote": True, "history": True})
        self.assertEqual(router.status("US_EQUITY", "P1")["status"], "live")

    def test_router_can_use_only_same_provider_cache_after_all_live_attempts_fail(self):
        provider = FakeProvider("P1", US_EQUITY)
        cache = MarketDataCache()
        router = MarketDataRouter(cache=cache)
        router.register(provider)
        router.fetch_window("US_EQUITY", "AAPL.US", "1d", limit=10)
        provider.error = RuntimeError("provider down")
        stale = router.fetch_window("US_EQUITY", "AAPL.US", "1d", limit=10)
        self.assertEqual(stale.provider_id, "P1")
        self.assertEqual(stale.meta.get("mode"), "cache")
        self.assertTrue(stale.meta.get("stale"))
