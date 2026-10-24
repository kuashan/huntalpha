"""V2.0.3: real ETF identity, account watchlist and existing chart boundaries."""
import io
import json
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import SimpleTestCase, TestCase

from .etf_discovery import ETFDiscoveryUnavailable, _record, _search_query, discover_etfs
from .models import MarketSymbol, WatchlistEntry


class ETFIdentityTests(SimpleTestCase):
    def test_china_etf_requires_verifiable_fund_name(self):
        cn = {"symbol": "510300.SS", "quoteType": "EQUITY",
              "longname": "Huatai-PineBridge CSI 300 ETF", "exchange": "SHH"}
        self.assertEqual(_record(cn)["code"], "SH.510300")
        self.assertEqual(_record({"symbol": "600519.SS", "quoteType": "EQUITY", "longname": "Stock Co"}), None)
        self.assertEqual(_record({"symbol": "510300.SS", "quoteType": "EQUITY", "longname": "Unknown"}), None)

    def test_hong_kong_and_us_etfs_not_stocks_or_crypto(self):
        self.assertEqual(_record({"symbol": "2800.HK", "quoteType": "ETF", "longname": "Tracker Fund"})["code"], "HK.02800")
        self.assertEqual(_record({"symbol": "SPY", "quoteType": "ETF", "longname": "SPDR ETF"})["code"], "US.SPY")
        self.assertIsNone(_record({"symbol": "AAPL", "quoteType": "EQUITY", "longname": "Apple Inc"}))
        self.assertIsNone(_record({"symbol": "BTC-USD", "quoteType": "CRYPTOCURRENCY", "longname": "Bitcoin"}))
        self.assertEqual(_search_query("HK.02800"), "2800.HK")
        self.assertEqual(_search_query("SH.510300"), "510300.SS")
        self.assertIsNone(_search_query("Alpha Company"))

    def test_network_query_is_bounded_and_cached(self):
        cache.clear()
        payload = {"quotes": [
            {"symbol": "SPY", "quoteType": "ETF", "longname": "SPDR S&P 500 ETF", "exchange": "PCX"},
            {"symbol": "AAPL", "quoteType": "EQUITY", "longname": "Apple", "exchange": "NMS"},
        ]}
        with patch("core.etf_discovery.urlopen", return_value=io.BytesIO(json.dumps(payload).encode())) as urlopen:
            rows = discover_etfs("SPY")
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["code"], "US.SPY")
            self.assertEqual(discover_etfs("SPY"), rows)
            self.assertEqual(urlopen.call_count, 1)

    def test_invalid_upstream_does_not_fabricate_etf(self):
        cache.clear()
        with patch("core.etf_discovery.urlopen", side_effect=TimeoutError("offline")):
            with self.assertRaises(ETFDiscoveryUnavailable):
                discover_etfs("QQQ")


class ETFWebTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="etf-member", password="safe-password-123")
        self.client.force_login(self.user)
        self.etfs = (
            {"code": "SH.510300", "name": "Huatai-PineBridge CSI 300 ETF", "market": "cn", "exchange": "SHH",
             "security_type": "ETF", "active": True, "provider": "yahoo-finance", "provider_symbol": "510300.SS"},
            {"code": "HK.02800", "name": "Tracker Fund Of Hong Kong", "market": "hk", "exchange": "HKG",
             "security_type": "ETF", "active": True, "provider": "yahoo-finance", "provider_symbol": "2800.HK"},
            {"code": "US.SPY", "name": "State Street SPDR S&P 500 ETF", "market": "us", "exchange": "PCX",
             "security_type": "ETF", "active": True, "provider": "yahoo-finance", "provider_symbol": "SPY"},
        )

    def test_three_market_search_discovers_real_etfs_without_writing(self):
        for info in self.etfs:
            with self.subTest(market=info["market"]), patch("core.views.discover_etfs", return_value=(info,)):
                response = self.client.get("/api/symbol-search/?q=" + info["code"])
                self.assertEqual(response.status_code, 200)
                found = next(item for item in response.json()["items"] if item["code"] == info["code"])
                self.assertEqual(found["market"], info["market"])
                self.assertEqual(found["security_type"], "ETF")
                self.assertFalse(found["watchlisted"])
                self.assertFalse(MarketSymbol.objects.filter(code=info["code"]).exists())

    def test_verified_etf_can_be_added_to_normal_watchlist(self):
        for info in self.etfs:
            with self.subTest(code=info["code"]), patch("core.views.lookup_etf", return_value=info):
                response = self.client.post("/api/watchlist/", data=json.dumps({"code": info["code"]}),
                                            content_type="application/json")
                self.assertEqual(response.status_code, 201)
                self.assertEqual(response.json()["item"]["code"], info["code"])
                self.assertEqual(MarketSymbol.objects.get(code=info["code"]).security_type, "ETF")
        self.assertEqual(WatchlistEntry.objects.filter(user=self.user).count(), 3)
        self.assertEqual({row["code"] for row in self.client.get("/api/watchlist/").json()["items"]},
                         {item["code"] for item in self.etfs})
        for info in self.etfs:
            with self.subTest(code=info["code"]):
                data = self.client.get(f'/api/symbols/{info["market"]}/?q=ETF').json()
                if info["market"] != "hk":  # Hong Kong vendor fund name need not include "ETF".
                    self.assertIn(info["code"], {row["code"] for row in data["items"]})
                else:
                    self.assertIn(info["code"], {row["code"] for row in self.client.get('/api/symbols/hk/?q=Tracker').json()["items"]})

    def test_unverified_or_unsupported_type_cannot_be_saved(self):
        with patch("core.views.lookup_etf", return_value=None):
            response = self.client.post("/api/watchlist/", data=json.dumps({"code": "US.FAKE"}),
                                        content_type="application/json")
        self.assertEqual(response.status_code, 404)
        self.assertFalse(MarketSymbol.objects.filter(code="US.FAKE").exists())
        MarketSymbol.objects.create(code="US.UNKNOWN", name="Unknown", market="us", security_type="OTHER",
                                    provider="yahoo-finance", active=True, provider_symbol="UNKNOWN")
        response = self.client.post("/api/watchlist/", data=json.dumps({"code": "US.UNKNOWN"}),
                                    content_type="application/json")
        self.assertEqual(response.status_code, 409)

    def test_etf_does_not_change_crypto_scope_or_stock_leaders(self):
        MarketSymbol.objects.create(**self.etfs[2], market_cap_currency="USD")
        MarketSymbol.objects.create(code="CC.BTC-USD", name="Bitcoin", market="crypto",
                                    security_type="CRYPTO_SPOT", active=True,
                                    provider="coinbase", provider_symbol="BTC-USD")
        self.assertEqual(self.client.get("/api/symbols/crypto/").json()["total"], 1)
        self.assertNotIn("US.SPY", {x["code"] for x in self.client.get("/api/market-leaders/us/").json()["items"]})
