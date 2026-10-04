from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase

from .marketdata import MarketDataRouter, US_EQUITY
from .marketdata.service import MarketDataService


class QuoteProvider:
    provider_id = "test-provider"
    provider_label_zh = "测试行情"
    profile = US_EQUITY

    def quote(self, symbol):
        return {"code": symbol, "price": 123.4, "source": self.provider_id, "status": "ready"}

    def fetch_window(self, symbol, timeframe, **kwargs):
        return {"completed": [{"time": 1, "close": 123.4}], "forming": None, "meta": {"mode": "historical"}}


class MarketDataApplicationTests(TestCase):
    def test_service_exposes_provider_neutral_quote_and_window(self):
        router = MarketDataRouter()
        router.register(QuoteProvider())
        service = MarketDataService(router=router)
        quote = service.quote_for_symbol("AAPL.US")
        window = service.window_for_symbol("AAPL.US", "日线", limit=100)
        self.assertEqual(quote["source"], "test-provider")
        self.assertEqual(window.provider_id, "test-provider")
        self.assertEqual(window.completed[0]["close"], 123.4)

    def test_views_do_not_import_a_provider_sdk(self):
        source = Path(__file__).with_name("views.py").read_text(encoding="utf-8")
        self.assertNotIn("from futu import", source)
        self.assertIn("marketdata.service", source)
