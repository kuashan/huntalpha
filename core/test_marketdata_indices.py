from threading import Barrier, BrokenBarrierError

from django.test import SimpleTestCase

from .marketdata.providers.base import MarketDataProviderError


class _QuoteProvider:
    def __init__(self, provider_id, profile, quotes=None, error=None):
        self.provider_id = provider_id
        self.provider_label_zh = provider_id
        self.profile = profile
        self.quotes = quotes or {}
        self.error = error
        self.calls = []

    def quote(self, symbol):
        self.calls.append(symbol)
        if self.error:
            raise self.error
        value = self.quotes.get(symbol)
        if value is None:
            raise MarketDataProviderError("provider has no real quote")
        return value


class UnifiedIndexSnapshotTests(SimpleTestCase):
    """Regression coverage for the no-Futu unified index path."""

    def test_cn_index_falls_back_to_next_unified_provider_without_futu(self):
        # This must fail if an index row is again treated as merely
        # "not configured" despite a healthy unified-provider fallback.
        from .marketdata.indices import UnifiedIndexSnapshotAdapter
        from .marketdata.profiles import CN_A_SHARE

        yahoo = _QuoteProvider("yahoo-finance", CN_A_SHARE, error=MarketDataProviderError("rate limited"))
        tencent = _QuoteProvider(
            "tencent-public",
            CN_A_SHARE,
            quotes={
                "SH.000001": {
                    "price": 3210.5,
                    "previous_close": 3200.0,
                    "open": 3205.0,
                    "high": 3222.0,
                    "low": 3198.0,
                    "updated_at": "2026-10-09 15:00:00",
                    "source": "tencent-public",
                    "data_status": "delayed",
                }
            },
        )
        adapter = UnifiedIndexSnapshotAdapter({"cn": (yahoo, tencent)})

        item = adapter.snapshot_item("shanghai")

        self.assertEqual(yahoo.calls, ["SH.000001"])
        self.assertEqual(tencent.calls, ["SH.000001"])
        self.assertEqual(item["status"], "ok")
        self.assertEqual(item["price"], 3210.5)
        self.assertEqual(item["change"], 10.5)
        self.assertEqual(item["change_percent"], 0.328125)
        self.assertEqual(item["source"], "tencent-public")
        self.assertNotEqual(item["source"], "futu-opend")

    def test_unavailable_index_never_falls_back_to_futu_or_a_proxy_price(self):
        from .marketdata.indices import UnifiedIndexSnapshotAdapter
        from .marketdata.profiles import US_EQUITY

        yahoo = _QuoteProvider("yahoo-finance", US_EQUITY, error=MarketDataProviderError("unavailable"))
        adapter = UnifiedIndexSnapshotAdapter({"us": (yahoo,)})

        item = adapter.snapshot_item("sp500")

        self.assertEqual(yahoo.calls, ["US.^GSPC"])
        self.assertEqual(item["status"], "unavailable")
        self.assertIsNone(item["price"])
        self.assertIsNone(item["change"])
        self.assertIsNone(item["change_percent"])
        self.assertNotEqual(item["source"], "futu-opend")

    def test_tencent_index_identity_preserves_verified_hk_index_symbol(self):
        from .marketdata.providers.tencent import tencent_symbol_for

        self.assertEqual(tencent_symbol_for("INDEX.HSI"), "hkHSI")
        self.assertEqual(tencent_symbol_for("INDEX.HSTECH"), "hkHSTECH")

    def test_snapshot_response_fetches_independent_indexes_concurrently(self):
        from .marketdata.indices import UnifiedIndexSnapshotAdapter
        from .marketdata.profiles import CN_A_SHARE

        barrier = Barrier(7)

        class ParallelProvider(_QuoteProvider):
            def quote(self, symbol):
                self.calls.append(symbol)
                try:
                    barrier.wait(timeout=2)
                except BrokenBarrierError as exc:
                    raise AssertionError("index snapshots were fetched serially") from exc
                return {
                    "price": 100.0,
                    "previous_close": 99.0,
                    "source": self.provider_id,
                    "data_status": "delayed",
                }

        provider = ParallelProvider("yahoo-finance", CN_A_SHARE)
        adapter = UnifiedIndexSnapshotAdapter({
            "cn": (provider,),
            "hk": (provider,),
            "us": (provider,),
        })

        payload = adapter.snapshot_response()
        items = [item for market in payload["markets"] for item in market["items"]]
        self.assertEqual(len(items), 7)
        self.assertTrue(all(item["status"] == "ok" for item in items))
        self.assertEqual(len(provider.calls), 7)
