import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.contrib.auth.models import AnonymousUser
from django.test import RequestFactory, SimpleTestCase

from .stock_fear_greed import FearGreedUnavailable, fetch_stock_fear_greed, provider_ticker
from .views import stock_fear_greed


class _FakeResponse:
    def __init__(self, data):
        self.data = json.dumps(data).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self, _size):
        return self.data


class FearGreedAdapterTests(SimpleTestCase):
    def test_market_ticker_mapping(self):
        cases = {
            "US.ORCL": "ORCL",
            "SH.600519": "600519.SS",
            "SZ.002315": "002315.SZ",
            "HK.00772": "0772.HK",
            "CC.BTC-USD": "BTC-USD",
            "CC.ETH-USDT": "ETH-USDT",
            "CC.BTCUSD": "BTC-USD",
        }
        for code, expected in cases.items():
            with self.subTest(code=code):
                self.assertEqual(provider_ticker(code), expected)
        for code in ("BJ.920522", "US.aapl?x=1", "https://127.0.0.1", "CC.BTC%2fUSD"):
            with self.subTest(code=code), self.assertRaises(FearGreedUnavailable):
                provider_ticker(code)

    def test_service_disabled_does_not_fetch_or_invent_a_score(self):
        with patch.dict("os.environ", {"SIFTALPHA_STOCK_FEAR_GREED_URL": ""}):
            with patch("core.stock_fear_greed.urlopen") as fetch:
                with self.assertRaises(FearGreedUnavailable) as caught:
                    fetch_stock_fear_greed("US.ORCL")
                self.assertEqual(caught.exception.status, "not_configured")
                fetch.assert_not_called()

    def test_adapts_real_upstream_json_without_recalculating(self):
        upstream = {
            "ticker": "ORCL",
            "latest": {"score": 76.43, "label": "极度贪婪", "date": "2026-10-23"},
            "latest_subscores": {"trend": 83.12, "macd": 66.1, "mfi": 0, "rsi": float("nan")},
        }
        with patch("core.stock_fear_greed.urlopen", return_value=_FakeResponse(upstream)) as fetch:
            result = fetch_stock_fear_greed("US.ORCL", service_url="http://stock-fear-greed:8000")
        self.assertEqual(result["score"], 76.43)
        self.assertEqual(result["date"], "2026-10-23")
        self.assertEqual(result["ticker"], "ORCL")
        self.assertEqual(result["subscores"], {"trend": 83.12, "macd": 66.1, "mfi": 0.0})
        request = fetch.call_args.args[0]
        self.assertIn("ticker=ORCL", request.full_url)
        self.assertIn("freq=1d", request.full_url)
        self.assertIn("window=252", request.full_url)

    def test_does_not_accept_wrong_symbol_missing_or_invalid_scores(self):
        cases = [
            {"ticker": "NVDA", "latest": {"score": 88, "date": "2026-10-23"}},
            {"ticker": "ORCL", "latest": None},
            {"ticker": "ORCL", "latest": {"score": float("nan"), "date": "2026-10-23"}},
            {"ticker": "ORCL", "latest": {"score": 101, "date": "2026-10-23"}},
        ]
        for payload in cases:
            with self.subTest(payload=payload):
                with patch("core.stock_fear_greed.urlopen", return_value=_FakeResponse(payload)):
                    with self.assertRaises(FearGreedUnavailable):
                        fetch_stock_fear_greed("US.ORCL", service_url="http://localhost:8000")

    def test_rejects_unexpected_service_url(self):
        for address in ("file:///etc/passwd", "http://user:pass@localhost:8000", "http://localhost:8000?x=y"):
            with self.subTest(address=address):
                with self.assertRaises(FearGreedUnavailable) as caught:
                    fetch_stock_fear_greed("US.ORCL", service_url=address)
                self.assertEqual(caught.exception.status, "invalid_configuration")

    def test_web_endpoint_rejects_anonymous_and_unknown_symbols(self):
        factory = RequestFactory()
        unauthenticated = factory.get("/api/stock-fear-greed/US.ORCL/")
        unauthenticated.user = AnonymousUser()
        unauthenticated.session = {}
        self.assertEqual(stock_fear_greed(unauthenticated, "US.ORCL").status_code, 401)

        visitor = factory.get("/api/stock-fear-greed/US.ORCL/")
        visitor.user = AnonymousUser()
        visitor.session = {"quantscope_visitor": True}
        with patch("core.views.MarketSymbol.objects.filter") as objects:
            objects.return_value.first.return_value = None
            self.assertEqual(stock_fear_greed(visitor, "US.ORCL").status_code, 404)

    def test_web_endpoint_reports_missing_optional_service(self):
        factory = RequestFactory()
        request = factory.get("/api/stock-fear-greed/US.ORCL/")
        request.user = AnonymousUser()
        request.session = {"quantscope_visitor": True}
        with patch("core.views.MarketSymbol.objects.filter") as objects:
            objects.return_value.first.return_value = SimpleNamespace(code="US.ORCL")
            with patch("core.views.fetch_stock_fear_greed", side_effect=FearGreedUnavailable("not_configured")):
                response = stock_fear_greed(request, "US.ORCL")
        self.assertEqual(response.status_code, 503)
        self.assertEqual(json.loads(response.content)["status"], "not_configured")
