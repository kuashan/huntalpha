import os
from types import SimpleNamespace
from unittest import TestCase, mock

from .marketdata import CN_A_SHARE, CRYPTO_24_7, HK_EQUITY, US_EQUITY
from .marketdata.providers.coinbase import CoinbaseMarketDataProvider
from .marketdata.providers.longbridge import LongbridgeMarketDataProvider
from .marketdata.providers.tushare import TushareMarketDataProvider


class FakeTushareClient:
    def __init__(self):
        self.calls = []

    def pro_bar(self, **kwargs):
        self.calls.append(kwargs)
        return [
            {
                "ts_code": kwargs["ts_code"],
                "trade_date": "20261001",
                "open": 10,
                "high": 11,
                "low": 9,
                "close": 10.5,
                "vol": 1000,
                "amount": 10500,
            }
        ]

    def realtime_quote(self, symbol):
        self.calls.append({"realtime_symbol": symbol})
        return [{"ts_code": symbol, "trade_time": "2026-10-04 09:31:00", "last": 10.5, "pre_close": 10, "open": 10, "high": 11, "low": 9, "vol": 100, "amount": 1050}]


class FakeLongbridgeContext:
    def quote(self, symbols):
        return [SimpleNamespace(symbol=symbols[0], last_done=123.4, volume=100, turnover=12340)]

    def candlesticks(self, symbol, period, adjust_type, count):
        return [SimpleNamespace(timestamp=1, open=10, high=11, low=9, close=10.5, volume=100)]


class MarketDataProviderTests(TestCase):
    def test_tushare_without_token_is_explicitly_unavailable(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            provider = TushareMarketDataProvider()
        self.assertEqual(provider.profile, CN_A_SHARE)
        self.assertEqual(provider.status()["status"], "not_configured")
        with self.assertRaisesRegex(RuntimeError, "Tushare token"):
            provider.fetch_window("600519.SH", "1d", limit=100)

    def test_tushare_maps_real_ohlcv_fields_without_fake_defaults(self):
        client = FakeTushareClient()
        provider = TushareMarketDataProvider(token="local-test-token", client=client)
        result = provider.fetch_window("600519.SH", "1d", limit=100)
        self.assertEqual(result["completed"][0]["close"], 10.5)
        self.assertEqual(result["completed"][0]["amount"], 10500)
        self.assertEqual(result["completed"][0]["volume"], 1000)
        self.assertEqual(client.calls[0]["ts_code"], "600519.SH")

    def test_tushare_quote_accepts_internal_symbol_and_returns_real_source(self):
        client = FakeTushareClient()
        provider = TushareMarketDataProvider(token="local-test-token", client=client)
        result = provider.quote("SH.600519")
        self.assertEqual(result["code"], "SH.600519")
        self.assertEqual(result["price"], 10.5)
        self.assertEqual(result["change"], 5.0)
        self.assertEqual(client.calls[-1]["realtime_symbol"], "600519.SH")

    def test_longbridge_without_token_is_explicitly_unavailable(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            provider = LongbridgeMarketDataProvider()
        self.assertEqual(provider.profile, HK_EQUITY)
        self.assertEqual(provider.status()["status"], "not_configured")
        self.assertFalse(provider.capabilities()["streaming"])

    def test_longbridge_history_without_token_reports_not_configured_before_sdk_probe(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            provider = LongbridgeMarketDataProvider(market=CN_A_SHARE)
        with self.assertRaises(RuntimeError) as raised:
            provider.fetch_window("SH.600519", "日线", limit=100)
        self.assertEqual(raised.exception.status, "not_configured")

    def test_longbridge_context_is_provider_neutral_at_boundary(self):
        provider = LongbridgeMarketDataProvider(
            token="local-test-token", context=FakeLongbridgeContext(), market=US_EQUITY
        )
        quote = provider.quote("AAPL.US")
        window = provider.fetch_window("AAPL.US", "1d", limit=100)
        self.assertEqual(quote["price"], 123.4)
        self.assertEqual(window["completed"][0]["close"], 10.5)
        self.assertEqual(window["meta"]["mode"], "historical")

    def test_coinbase_remains_public_and_credential_free(self):
        provider = CoinbaseMarketDataProvider()
        self.assertEqual(provider.profile, CRYPTO_24_7)
        self.assertEqual(provider.status()["status"], "ready")
        self.assertTrue(provider.capabilities()["public"])
