"""V2.0.1: all-source exchange-calendar and source-switch regressions."""
from datetime import datetime, timezone
from unittest import TestCase
from zoneinfo import ZoneInfo

from .marketdata import CN_A_SHARE, CRYPTO_24_7, HK_EQUITY, US_EQUITY, MarketDataRouter
from .marketdata.calendar import canonical_calendar_time
from .marketdata.providers.longbridge import _stamp as longbridge_stamp
from .marketdata.providers.tushare import _timestamp as tushare_stamp
from .realtime.contracts import NormalizedBar
from .realtime.state import RealtimeStateStore


def local_timestamp(year, month, day, hour, minute, zone):
    return int(datetime(year, month, day, hour, minute, tzinfo=ZoneInfo(zone)).timestamp())


class Source:
    def __init__(self, profile, provider_id, timestamp):
        self.profile = profile
        self.provider_id = provider_id
        self.provider_label_zh = provider_id
        self.timestamp = timestamp

    def fetch_window(self, symbol, timeframe, **kwargs):
        return {
            "completed": [{
                "time": self.timestamp, "open": 24.4, "high": 26.4,
                "low": 24.22, "close": 26.4, "volume": 196566,
            }],
            "forming": None,
        }


class CalendarSourceTests(TestCase):
    def test_yahoo_and_tencent_share_same_a_share_trading_day(self):
        midnight = local_timestamp(2026, 10, 23, 0, 0, "Asia/Shanghai")
        opening = local_timestamp(2026, 10, 23, 9, 30, "Asia/Shanghai")
        selected = {"provider": "yahoo-finance"}
        router = MarketDataRouter(selection_resolver=lambda _: selected["provider"])
        router.register(Source(CN_A_SHARE, "yahoo-finance", opening))
        router.register(Source(CN_A_SHARE, "tencent-public", midnight))
        first = router.fetch_window("CN_A_SHARE", "SZ.002315", "日线")
        selected["provider"] = "tencent-public"
        second = router.fetch_window("CN_A_SHARE", "SZ.002315", "日线")
        self.assertEqual(first.completed[0]["time"], midnight)
        self.assertEqual(first.completed, second.completed)
        self.assertEqual(first.completed[0]["open"], 24.4)
        self.assertEqual(first.completed[0]["volume"], 196566)
        self.assertNotEqual(first.provider_id, second.provider_id)

    def test_every_market_uses_its_exchange_timezone_not_browser_or_server_timezone(self):
        for profile in (CN_A_SHARE, HK_EQUITY, US_EQUITY, CRYPTO_24_7):
            with self.subTest(profile=profile.market_id):
                midnight = local_timestamp(2026, 10, 23, 0, 0, profile.timezone)
                morning = local_timestamp(2026, 10, 23, 9, 30, profile.timezone)
                self.assertEqual(canonical_calendar_time(morning, profile.market_id, "日线"), midnight)
                self.assertEqual(canonical_calendar_time(midnight, profile.market_id, "日线"), midnight)

    def test_us_dst_and_iso_week_month_boundaries(self):
        for month, day in ((3, 6), (3, 9), (11, 2)):
            source = local_timestamp(2026, month, day, 9, 30, "America/New_York")
            aligned = canonical_calendar_time(source, "US_EQUITY", "日线")
            local = datetime.fromtimestamp(aligned, ZoneInfo("America/New_York"))
            self.assertEqual((local.year, local.month, local.day, local.hour), (2026, month, day, 0))
        stamp = local_timestamp(2027, 1, 1, 9, 30, "Asia/Shanghai")
        week = canonical_calendar_time(stamp, "CN_A_SHARE", "周线")
        month = canonical_calendar_time(stamp, "CN_A_SHARE", "月线")
        self.assertEqual(datetime.fromtimestamp(week, ZoneInfo("Asia/Shanghai")).date().isoformat(), "2026-12-28")
        self.assertEqual(datetime.fromtimestamp(month, ZoneInfo("Asia/Shanghai")).date().isoformat(), "2027-01-01")

    def test_intraday_timestamp_remains_exact(self):
        stamp = local_timestamp(2026, 10, 23, 9, 31, "Asia/Shanghai")
        for market in ("CN_A_SHARE", "HK_EQUITY", "US_EQUITY", "CRYPTO"):
            self.assertEqual(canonical_calendar_time(stamp, market, "1分"), stamp)

    def test_same_provider_duplicate_bucket_does_not_combine_ohlcv(self):
        stamp = local_timestamp(2026, 10, 23, 9, 30, "Asia/Shanghai")
        router = MarketDataRouter()
        source = Source(CN_A_SHARE, "yahoo-finance", stamp)
        def fetch(symbol, timeframe, **kwargs):
            return {
                "completed": [
                    {"time": stamp, "open": 10, "high": 11, "low": 9, "close": 10, "volume": 5},
                    {"time": stamp + 60, "open": 20, "high": 22, "low": 18, "close": 21, "volume": 7},
                ],
                "forming": None,
            }
        source.fetch_window = fetch
        router.register(source)
        result = router.fetch_window("CN_A_SHARE", "SZ.002315", "日线")
        self.assertEqual(len(result.completed), 1)
        self.assertEqual(result.completed[0]["open"], 20)
        self.assertEqual(result.completed[0]["volume"], 7)

    def test_tushare_and_longbridge_naive_datetime_use_exchange_clock(self):
        target = local_timestamp(2026, 10, 23, 0, 0, "Asia/Shanghai")
        for value in ("20261023", "2026-10-23", "2026-10-23 00:00:00"):
            self.assertEqual(tushare_stamp(value), target)
        self.assertEqual(longbridge_stamp(datetime(2026, 10, 23, 0, 0), "Asia/Shanghai"), target)
        self.assertEqual(longbridge_stamp("2026-10-23T00:00:00", "Asia/Shanghai"), target)

    def test_realtime_source_switch_resets_last_closed_and_current_provider(self):
        store = RealtimeStateStore()
        key = ("public-market", "cn", "SZ.002315", "日线")
        yahoo_time = local_timestamp(2026, 10, 23, 9, 30, "Asia/Shanghai")
        tencent_time = local_timestamp(2026, 10, 23, 0, 0, "Asia/Shanghai")
        def bar(provider, timestamp):
            return NormalizedBar(provider=provider, market="cn", symbol="SZ.002315", period="日线",
                                 time=timestamp, open=24.4, high=26.4, low=24.22, close=26.4,
                                 volume=196566, is_closed=True)
        first, _ = store.apply_bar(key, bar("yahoo-finance", yahoo_time))
        second, result = store.apply_bar(key, bar("tencent-public", tencent_time))
        self.assertEqual(first.current_bar.time, second.current_bar.time)
        self.assertEqual(second.current_bar.provider, "tencent-public")
        self.assertIsNone(second.last_closed_bar)
        self.assertEqual(result.relation, "initial")
        self.assertGreater(second.revision, first.revision)
