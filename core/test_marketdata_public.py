import json
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from unittest import TestCase, mock

from .marketdata.profiles import CN_A_SHARE, HK_EQUITY, US_EQUITY
from .marketdata.providers.yahoo import YahooFinanceMarketDataProvider, yahoo_symbol_for, _is_complete
from .marketdata.providers.tencent import TencentPublicMarketDataProvider, tencent_symbol_for
from .marketdata.service import build_market_data_router
from .realtime.public_provider import PublicMarketRealtimeProvider


class PublicMarketDataProviderTests(TestCase):
    def test_public_symbol_mapping_covers_required_markets(self):
        self.assertEqual(yahoo_symbol_for("SH.600519"), "600519.SS")
        self.assertEqual(yahoo_symbol_for("SZ.000001"), "000001.SZ")
        self.assertEqual(yahoo_symbol_for("HK.00700"), "0700.HK")
        self.assertEqual(yahoo_symbol_for("US.AAPL"), "AAPL")
        self.assertEqual(tencent_symbol_for("SH.600519"), "sh600519")
        self.assertEqual(tencent_symbol_for("SZ.000001"), "sz000001")
        self.assertEqual(tencent_symbol_for("HK.700"), "hk00700")

    def test_yahoo_provider_keeps_completed_and_forming_separate(self):
        payload = {
            "chart": {
                "result": [{
                    "meta": {
                        "exchangeTimezoneName": "Asia/Shanghai",
                        "exchangeDataDelayedBy": 15,
                        "currentTradingPeriod": {"regular": {"start": 1000, "end": 2000}},
                    },
                    "timestamp": [100, 1500],
                    "indicators": {"quote": [{
                        "open": [10, 11], "high": [12, 13], "low": [9, 10],
                        "close": [11, 12], "volume": [100, 200],
                    }]},
                }],
                "error": None,
            }
        }
        provider = YahooFinanceMarketDataProvider(CN_A_SHARE, minimum_completed_bars=1)
        with mock.patch.object(provider, "_request_chart", return_value=payload):
            result = provider.fetch_window("SH.600519", "日线", now_ts=1600)
        self.assertEqual(len(result["completed"]), 1)
        self.assertEqual(result["completed"][0]["time"], 100)
        self.assertEqual(result["forming"]["close"], 12.0)
        self.assertEqual(result["meta"]["data_status"], "delayed")
        self.assertEqual(result["meta"]["delay_seconds"], 15)

    def test_yahoo_daily_bar_closes_at_exchange_session_end(self):
        tz = ZoneInfo("Asia/Shanghai")
        session_start = int(datetime(2026, 10, 19, 9, 30, tzinfo=tz).timestamp())
        session_end = int(datetime(2026, 10, 19, 15, 0, tzinfo=tz).timestamp())
        at = lambda hour, minute: int(datetime(2026, 10, 19, hour, minute, tzinfo=tz).timestamp())
        self.assertFalse(_is_complete(session_start, "日线", CN_A_SHARE, at(14, 59), session_start, session_end))
        self.assertTrue(_is_complete(session_start, "日线", CN_A_SHARE, at(15, 0), session_start, session_end))
        self.assertTrue(_is_complete(session_start, "日线", CN_A_SHARE, at(15, 30), session_start, session_end))

        provider = YahooFinanceMarketDataProvider(CN_A_SHARE, minimum_completed_bars=1)
        payload = {
            "chart": {"result": [{
                "meta": {"currentTradingPeriod": {"regular": {"start": session_start, "end": session_end}}},
                "timestamp": [session_start],
                "indicators": {"quote": [{
                    "open": [10], "high": [12], "low": [9], "close": [11], "volume": [100],
                }]},
            }], "error": None},
        }
        with mock.patch.object(provider, "_request_chart", return_value=payload):
            result = provider.fetch_window("SH.600519", "日线", now_ts=at(15, 30))
        self.assertEqual([bar["time"] for bar in result["completed"]], [session_start])
        self.assertIsNone(result["forming"])

    def test_yahoo_week_month_are_not_completed_by_midperiod_daily_close(self):
        tz = ZoneInfo("Asia/Shanghai")
        stamp = lambda day, hour=15: int(datetime(2026, 10, day, hour, tzinfo=tz).timestamp())
        # Monday afternoon does not complete that calendar week or month.
        self.assertFalse(_is_complete(stamp(19, 9), "周线", CN_A_SHARE, stamp(19, 16), None, None))
        self.assertFalse(_is_complete(stamp(19, 9), "月线", CN_A_SHARE, stamp(19, 16), None, None))
        self.assertTrue(_is_complete(stamp(19, 9), "周线", CN_A_SHARE, stamp(26, 9), None, None))
        self.assertTrue(_is_complete(stamp(19, 9), "月线", CN_A_SHARE, int(datetime(2026, 11, 2, 9, tzinfo=tz).timestamp()), None, None))

    def test_yahoo_us_daily_close_uses_new_york_dst(self):
        tz = ZoneInfo("America/New_York")
        for month, day in ((3, 9), (11, 2)):
            with self.subTest(month=month):
                start = int(datetime(2026, month, day, 9, 30, tzinfo=tz).timestamp())
                end = int(datetime(2026, month, day, 16, 0, tzinfo=tz).timestamp())
                before = int(datetime(2026, month, day, 15, 59, tzinfo=tz).timestamp())
                self.assertFalse(_is_complete(start, "日线", US_EQUITY, before, start, end))
                self.assertTrue(_is_complete(start, "日线", US_EQUITY, end, start, end))

    def test_yahoo_quote_uses_current_market_change_not_long_history_chart_previous_close(self):
        payload = {
            "chart": {
                "result": [{
                    "meta": {
                        "regularMarketPrice": 24.73,
                        "regularMarketChangePercent": 2.402,
                        # Yahoo returns the beginning-of-window value here for
                        # long range requests, not the latest session close.
                        "chartPreviousClose": 13.473,
                    },
                    "indicators": {"quote": [{"close": [13.473, 24.15, 24.73]}]},
                }],
                "error": None,
            }
        }
        provider = YahooFinanceMarketDataProvider(CN_A_SHARE)
        with mock.patch.object(provider, "_request_chart", return_value=payload):
            result = provider.quote("SZ.002315")
        self.assertEqual(result["price"], 24.73)
        self.assertEqual(result["previous_close"], 24.15)
        self.assertEqual(result["change"], 2.402)

    def test_tencent_daily_payload_is_normalized_without_credentials(self):
        provider = TencentPublicMarketDataProvider(CN_A_SHARE)
        payload = {"code": 0, "data": {"sh600519": {"qfqday": [["2026-10-01", "10", "11", "12", "9", "100"]]}}}
        with mock.patch.object(provider, "_request_json", return_value=payload):
            result = provider.fetch_window("SH.600519", "日线", minimum_completed_bars=1)
        self.assertEqual(result["completed"][0]["open"], 10.0)
        self.assertEqual(result["completed"][0]["close"], 11.0)
        self.assertEqual(result["meta"]["data_status"], "delayed")

    def test_default_router_prioritizes_public_sources_and_keeps_private_optional(self):
        router = build_market_data_router()
        self.assertEqual(router.provider_ids("CN_A_SHARE")[:2], ("yahoo-finance", "tencent-public"))
        self.assertEqual(router.provider_ids("HK_EQUITY")[:2], ("yahoo-finance", "tencent-public"))
        self.assertEqual(router.provider_ids("US_EQUITY")[0], "yahoo-finance")
        self.assertNotIn("futu-opend", router.provider_ids("CN_A_SHARE"))

    def test_router_quote_fails_over_whole_quote_without_merging(self):
        router = build_market_data_router()
        first = mock.Mock()
        first.provider_id = "first-public"
        first.quote.side_effect = RuntimeError("temporary")
        second = mock.Mock()
        second.provider_id = "second-public"
        second.quote.return_value = {"price": 99.0, "source": "second-public", "data_status": "delayed"}
        first.profile = CN_A_SHARE
        second.profile = CN_A_SHARE
        router._providers[CN_A_SHARE.market_id] = [first, second]
        result = router.quote(CN_A_SHARE.market_id, "SH.600519")
        self.assertEqual(result["source"], "second-public")
        self.assertEqual(result["price"], 99.0)

    def test_public_realtime_uses_period_candle_and_preserves_delayed_metadata(self):
        from .marketdata.contracts import MarketDataFetch

        timestamp = int(datetime(2026, 10, 19, 14, 30, tzinfo=ZoneInfo("Asia/Shanghai")).timestamp())
        source = {
            "time": timestamp, "open": 10, "high": 11, "low": 9, "close": 10.5,
            "volume": 20,
        }
        class FakeRouter:
            def __init__(self):
                self.calls = []

            def fetch_window(self, market, symbol, period):
                self.calls.append((market, symbol, period))
                return MarketDataFetch(
                    market_id=market, provider_id="yahoo-finance", provider_label_zh="Yahoo",
                    symbol=symbol, timeframe=period, completed=[], forming=source,
                    meta={"data_status": "delayed"},
                )

            def quote(self, *args):
                raise AssertionError("不能使用全天报价构造分钟 K 线")

        router = FakeRouter()
        provider = PublicMarketRealtimeProvider(router, poll_interval=1)
        event = []
        provider._callbacks[("SH.600519", "1分")].add(event.append)
        provider.poll_once()
        provider.poll_once()
        self.assertEqual(provider.poll_interval, 60.0)
        self.assertEqual(router.calls, [
            ("CN_A_SHARE", "SH.600519", "1分"),
            ("CN_A_SHARE", "SH.600519", "1分"),
        ])
        self.assertEqual(len(event), 1)  # Unchanged real candle should not be re-sent.
        self.assertEqual(event[0].time, timestamp)
        self.assertEqual((event[0].open, event[0].high, event[0].low, event[0].close),
                         (10, 11, 9, 10.5))
        self.assertEqual(event[0].provider, "yahoo-finance")
        self.assertEqual(event[0].data_status, "delayed")
        self.assertEqual(event[0].mode, "polling")
        self.assertFalse(event[0].is_closed)
        self.assertEqual(event[0].event_kind, "authoritative")

    def test_public_realtime_closed_candle_uses_provider_timestamp_not_utc_bucket(self):
        from .marketdata.contracts import MarketDataFetch

        # Yahoo A-share daily bars use their real exchange-session timestamp (09:30).
        tz = ZoneInfo("Asia/Shanghai")
        stamp = int(datetime(2026, 10, 19, 9, 30, tzinfo=tz).timestamp())
        bar = {"time": stamp, "open": 9, "high": 11, "low": 8, "close": 10, "volume": 20}
        router = mock.Mock()
        router.fetch_window.return_value = MarketDataFetch(
            market_id="CN_A_SHARE", provider_id="yahoo-finance", provider_label_zh="Yahoo",
            symbol="SH.600519", timeframe="日线", completed=[bar],
            meta={"data_status": "historical"},
        )
        provider = PublicMarketRealtimeProvider(router, poll_interval=60)
        result = provider.latest_snapshot("SH.600519", "日线")
        self.assertEqual(result.time, stamp)
        self.assertTrue(result.is_closed)
        self.assertEqual(result.open, 9)
        router.quote.assert_not_called()

    def test_public_realtime_never_fabricates_incomplete_or_cached_candles(self):
        from .marketdata.contracts import MarketDataFetch
        from .realtime.provider import RealtimeProviderError

        router = mock.Mock()
        base = dict(
            market_id="CN_A_SHARE", provider_id="yahoo-finance", provider_label_zh="Yahoo",
            symbol="SH.600519", timeframe="1分",
        )
        provider = PublicMarketRealtimeProvider(router, poll_interval=60)
        router.fetch_window.return_value = MarketDataFetch(
            **base, completed=[], forming=None, meta={},
        )
        with self.assertRaises(RealtimeProviderError):
            provider.latest_snapshot("SH.600519", "1分")
        router.fetch_window.return_value = MarketDataFetch(
            **base, completed=[], forming={"time": 100, "high": 11, "low": 8, "close": 10},
            meta={},
        )
        with self.assertRaises(RealtimeProviderError):
            provider.latest_snapshot("SH.600519", "1分")
        router.fetch_window.return_value = MarketDataFetch(
            **base, completed=[{"time": 100, "open": 9, "high": 11, "low": 8, "close": 10}],
            forming=None, meta={"stale": True, "mode": "cache"},
        )
        with self.assertRaises(RealtimeProviderError):
            provider.latest_snapshot("SH.600519", "1分")
        router.quote.assert_not_called()
