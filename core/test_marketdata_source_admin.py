"""V1.1.5 admin market-source choices and per-request routing contracts."""
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from .marketdata import CN_A_SHARE, CRYPTO_24_7, HK_EQUITY, US_EQUITY, MarketDataRouter
from .marketdata.selection import selected_provider
from .models import MarketDataSourceSetting


class Source:
    def __init__(self, market, name, *, fail=False):
        self.profile = market
        self.provider_id = name
        self.provider_label_zh = name
        self.fail = fail
        self.calls = 0

    def quote(self, symbol):
        self.calls += 1
        if self.fail:
            raise RuntimeError("source unavailable")
        return {"code": symbol, "price": 2, "source": self.provider_id}

    def fetch_window(self, symbol, timeframe, **kwargs):
        self.calls += 1
        if self.fail:
            raise RuntimeError("source unavailable")
        return {"completed": [{"time": 1, "close": 2}], "forming": None}


class SourceSelectionTests(TestCase):
    def setUp(self):
        self.router = MarketDataRouter(selection_resolver=selected_provider)
        self.first = Source(US_EQUITY, "yahoo-finance", fail=True)
        self.backup = Source(US_EQUITY, "longbridge")
        self.router.register(self.first)
        self.router.register(self.backup)
        self.hk = Source(HK_EQUITY, "yahoo-finance")
        self.router.register(self.hk)

    def test_auto_preserves_fallback_and_market_independence(self):
        self.assertEqual(self.router.quote("US_EQUITY", "US.AAPL")["source"], "longbridge")
        self.assertEqual(self.router.provider_ids("HK_EQUITY"), ("yahoo-finance",))

    def test_manual_choice_is_strict_for_quotes_and_kline(self):
        MarketDataSourceSetting.objects.create(market="us", provider="yahoo-finance")
        self.assertEqual(self.router.provider_ids("US_EQUITY"), ("yahoo-finance",))
        with self.assertRaises(Exception):
            self.router.quote("US_EQUITY", "US.AAPL")
        with self.assertRaises(Exception):
            self.router.fetch_window("US_EQUITY", "US.AAPL", "日线")
        self.assertEqual(self.backup.calls, 0)
        self.assertEqual(self.router.provider_ids("HK_EQUITY"), ("yahoo-finance",))
        # Existing router observes newly saved configuration without restart.
        MarketDataSourceSetting.objects.filter(market="us").update(provider="longbridge")
        self.assertEqual(self.router.quote("US_EQUITY", "US.AAPL")["source"], "longbridge")
        self.assertEqual(self.router.providers_for("US_EQUITY"), (self.backup,))

    def test_invalid_persisted_source_fails_closed(self):
        MarketDataSourceSetting.objects.create(market="us", provider="coinbase")
        with self.assertRaises(ValueError):
            self.router.quote("US_EQUITY", "US.AAPL")

    def test_crypto_only_exposes_coinbase_or_auto(self):
        record = MarketDataSourceSetting(market="crypto", provider="yahoo-finance")
        from django.core.exceptions import ValidationError
        with self.assertRaises(ValidationError):
            record.full_clean()


class SourceAdminTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.superuser = User.objects.create_superuser(username="source-admin", email="source-admin@example.com", password="pass")
        self.staff = User.objects.create_user(username="source-staff", password="pass", is_staff=True)
        self.path = reverse("admin:core_marketdatasourcesetting_changelist")

    def test_only_superuser_can_read_and_save_four_choices(self):
        self.client.force_login(self.staff)
        self.assertEqual(self.client.get(self.path).status_code, 403)
        self.assertEqual(self.client.post(self.path, {"us": "longbridge"}).status_code, 403)
        self.assertEqual(MarketDataSourceSetting.objects.count(), 0)
        self.client.force_login(self.superuser)
        view = self.client.get(self.path)
        self.assertEqual(view.status_code, 200)
        for label in ("美股", "沪深 A 股", "港股", "加密货币"):
            self.assertContains(view, label)
        saved = self.client.post(self.path, {
            "us": "longbridge", "cn": "tushare", "hk": "tencent-public", "crypto": "coinbase",
        })
        self.assertEqual(saved.status_code, 302)
        self.assertEqual(
            dict(MarketDataSourceSetting.objects.values_list("market", "provider")),
            {"us": "longbridge", "cn": "tushare", "hk": "tencent-public", "crypto": "coinbase"},
        )
        self.assertEqual(selected_provider("CN_A_SHARE"), "tushare")

    def test_invalid_market_provider_never_partially_saves(self):
        self.client.force_login(self.superuser)
        view = self.client.post(self.path, {
            "us": "longbridge", "cn": "coinbase", "hk": "auto", "crypto": "coinbase",
        })
        self.assertEqual(view.status_code, 200)
        self.assertEqual(MarketDataSourceSetting.objects.count(), 0)
