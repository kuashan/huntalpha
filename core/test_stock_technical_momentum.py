"""Targeted contracts for the original MIT six-factor analyzer and data adapter."""
from datetime import date, datetime, time, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import Mock, patch
from zoneinfo import ZoneInfo
import json

import pandas as pd
from django.contrib.auth.models import AnonymousUser
from django.test import RequestFactory, SimpleTestCase

from .stock_technical_momentum import (
    TechnicalMomentumUnavailable, _bar, analyze_technical_momentum,
)
from .vendor.daily_stock_analysis.stock_analyzer import StockTrendAnalyzer
from .views import stock_technical_momentum


def fake_bars(zone="America/New_York", ending=date(2026, 10, 23), count=120):
    tz = ZoneInfo(zone)
    rows = []
    for index in range(count):
        day = ending - timedelta(days=(count - index - 1))
        close = 40.0 + index * 0.07 + (index % 9) * 0.09
        rows.append({
            "time": int(datetime.combine(day, time(12, 0), tzinfo=tz).timestamp()),
            "open": close - 0.2, "high": close + 0.7,
            "low": close - 0.8, "close": close,
            "volume": 1000000.0 + (index % 11) * 20000.0,
            "provider": "test", "period": "日线",
        })
    return rows


def fake_service(bars, *, forming=None, quote=None, provider="test", stale=False):
    obj = Mock()
    obj.window_for_symbol.return_value = SimpleNamespace(
        completed=bars, forming=forming, provider_id=provider,
        meta={"stale": stale},
    )
    obj.quote_for_symbol.return_value = quote
    return obj


class TechnicalMomentumDataTests(SimpleTestCase):
    def test_original_vendor_score_and_six_dimensions_are_unmodified(self):
        bars = fake_bars()
        service = fake_service(bars)
        now = datetime(2026, 10, 24, 5, tzinfo=timezone.utc)  # Sat, US closed
        output = analyze_technical_momentum("US.ORCL", service=service, now=now)
        original = StockTrendAnalyzer().analyze(
            pd.DataFrame([
                {"date": datetime.fromtimestamp(bar["time"], ZoneInfo("America/New_York")).date().isoformat(),
                 **{key: bar[key] for key in ("open", "high", "low", "close", "volume")}}
                for bar in bars
            ]), "US.ORCL")
        self.assertEqual(output["score"], original.signal_score)
        self.assertEqual(output["signal"], original.buy_signal.value)
        from .vendor.daily_stock_analysis.decision_scale import decision_band_for_score
        self.assertEqual(output["score_band"], decision_band_for_score(original.signal_score).signal_key)
        self.assertEqual(output["period"], "1d")
        self.assertEqual([d["max_score"] for d in output["dimensions"]], [30, 20, 15, 10, 15, 10])
        self.assertEqual(len(output["dimensions"]), 6)
        self.assertFalse(output["intraday"])
        service.window_for_symbol.assert_called_once_with("US.ORCL", "日线", limit=120)
        service.quote_for_symbol.assert_not_called()

    def test_same_symbol_same_provider_fresh_quote_updates_current_daily_candle(self):
        rows = fake_bars()
        now = datetime(2026, 10, 23, 15, 10, tzinfo=timezone.utc)  # 11:10 ET
        quote = {
            "code": "US.ORCL", "source": "test",
            "updated_at": int(now.timestamp()) - 20,
            "price": rows[-1]["close"] + 4.5, "high": rows[-1]["high"] + 5,
            "low": rows[-1]["low"], "volume": rows[-1]["volume"] + 90000,
        }
        service = fake_service(rows, quote=quote)
        current = analyze_technical_momentum("US.ORCL", service=service, now=now)
        baseline = analyze_technical_momentum("US.ORCL", service=fake_service(rows, quote=None), now=now)
        self.assertTrue(current["intraday"])
        self.assertEqual(current["date"], "2026-10-23")
        self.assertNotEqual(current["dimensions"][1]["detail"], baseline["dimensions"][1]["detail"])
        self.assertEqual(current["source"], "ZhuLinsen/daily_stock_analysis")

    def test_different_provider_or_stale_quote_cannot_change_score(self):
        rows = fake_bars()
        now = datetime(2026, 10, 23, 15, 10, tzinfo=timezone.utc)
        quote = {"code": "US.ORCL", "source": "other", "updated_at": int(now.timestamp()),
                 "price": 9999, "volume": 400000}
        mismatch = analyze_technical_momentum("US.ORCL", service=fake_service(rows, quote=quote), now=now)
        quote["source"] = "test"
        quote["updated_at"] = int(now.timestamp()) - 86400
        stale = analyze_technical_momentum("US.ORCL", service=fake_service(rows, quote=quote), now=now)
        self.assertEqual(mismatch["score"], stale["score"])
        self.assertEqual(mismatch["dimensions"], stale["dimensions"])

    def test_crypto_daily_candle_not_overwritten_by_rolling_24h_quote(self):
        bars = fake_bars(zone="UTC", ending=date(2026, 10, 23))
        now = datetime(2026, 10, 23, 15, tzinfo=timezone.utc)
        service = fake_service(bars, quote={"code": "CC.BTC-USD", "source": "test", "price": 9999})
        result = analyze_technical_momentum("CC.BTC-USD", service=service, now=now)
        self.assertTrue(result["intraday"])
        service.quote_for_symbol.assert_not_called()

    def test_incomplete_or_stale_data_fails_closed(self):
        now = datetime(2026, 10, 24, tzinfo=timezone.utc)
        invalid = fake_bars(count=60)
        invalid[-1]["volume"] = None
        cases = [(fake_service(fake_bars(count=59)), "insufficient_history"),
                 (fake_service(invalid), "insufficient_history"),
                 (fake_service(fake_bars(), stale=True), "unavailable")]
        for service, expected in cases:
            with self.subTest(expected=expected), self.assertRaises(TechnicalMomentumUnavailable) as caught:
                analyze_technical_momentum("US.ORCL", service=service, now=now)
            self.assertEqual(caught.exception.status, expected)

    def test_invalid_provider_ohlcv_is_not_silently_zeroed(self):
        data = fake_bars()[0]
        data["high"] = data["low"] - 1
        self.assertIsNone(_bar(data, ZoneInfo("America/New_York"), "test"))

    def test_all_four_market_profiles_are_covered(self):
        cases = {
            "US.ORCL": ("America/New_York", date(2026, 10, 23)),
            "SH.600519": ("Asia/Shanghai", date(2026, 10, 23)),
            "SZ.002315": ("Asia/Shanghai", date(2026, 10, 23)),
            "HK.00700": ("Asia/Hong_Kong", date(2026, 10, 23)),
            "CC.BTC-USD": ("UTC", date(2026, 10, 23)),
        }
        for code, (zone, day) in cases.items():
            with self.subTest(code=code):
                output = analyze_technical_momentum(code, service=fake_service(fake_bars(zone, day)),
                                                    now=datetime(2026, 10, 24, 5, tzinfo=timezone.utc))
                self.assertEqual(output["code"], code)
                self.assertIsInstance(output["score"], int)
                self.assertGreaterEqual(output["score"], 0)
                self.assertLessEqual(output["score"], 100)


class TechnicalMomentumApiTests(SimpleTestCase):
    def _request(self, *, visitor=False):
        req = RequestFactory().get("/api/stock-technical-momentum/US.ORCL/")
        req.user = AnonymousUser()
        req.session = {"quantscope_visitor": True} if visitor else {}
        return req

    def test_anonymous_is_blocked_before_provider_access(self):
        with patch("core.views.analyze_technical_momentum") as score:
            response = stock_technical_momentum(self._request(), "US.ORCL")
            self.assertEqual(response.status_code, 401)
            score.assert_not_called()

    def test_catalog_symbol_required_and_no_fake_score(self):
        with patch("core.views.MarketSymbol.objects.filter") as query:
            query.return_value.first.return_value = None
            response = stock_technical_momentum(self._request(visitor=True), "US.ORCL")
        self.assertEqual(response.status_code, 404)
        self.assertEqual(json.loads(response.content)["status"], "unknown_symbol")

    def test_upstream_failure_reports_503(self):
        with patch("core.views.MarketSymbol.objects.filter") as query, patch(
            "core.views.analyze_technical_momentum", side_effect=TechnicalMomentumUnavailable("unavailable")
        ):
            query.return_value.first.return_value = SimpleNamespace(code="US.ORCL")
            response = stock_technical_momentum(self._request(visitor=True), "US.ORCL")
        self.assertEqual(response.status_code, 503)
        self.assertEqual(json.loads(response.content)["status"], "unavailable")
