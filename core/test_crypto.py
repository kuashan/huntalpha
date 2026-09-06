import json
import inspect
import time
from datetime import datetime, timezone
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import Client, SimpleTestCase, TestCase

from .crypto_provider import (
    COINBASE_REST_BASE,
    CoinbaseApiError,
    CoinbaseCryptoCatalogAdapter,
    CoinbaseRealtimeProvider,
    aggregate_crypto_bars,
    fetch_crypto_historical_bars,
)
from .models import MarketSymbol, WatchlistEntry
from .realtime.router import MarketDataProviderRouter
from .symbol_catalog import (
    COINBASE_PROVIDER,
    ProviderCatalogSnapshot,
    ProviderSymbol,
    ProviderSyncError,
    apply_catalog_snapshot,
)


def candle(timestamp, open_price, high, low, close, volume=1):
    # Coinbase Exchange returns [time, low, high, open, close, volume].
    return [timestamp, low, high, open_price, close, volume]


class CryptoProviderContractTests(SimpleTestCase):
    def test_catalog_uses_real_coinbase_product_metadata_and_internal_mapping(self):
        class Client:
            def product(self, product_id):
                return {
                    "id": product_id,
                    "display_name": f"{product_id} spot",
                    "status": "online",
                }

        snapshot = CoinbaseCryptoCatalogAdapter(client=Client()).fetch_market()
        self.assertEqual(snapshot.provider, COINBASE_PROVIDER)
        self.assertEqual([item.code for item in snapshot.symbols], ["CC.BTC-USD", "CC.ETH-USD"])
        self.assertEqual([item.provider_symbol for item in snapshot.symbols], ["BTC-USD", "ETH-USD"])
        self.assertTrue(all(item.security_type == "CRYPTO_SPOT" for item in snapshot.symbols))
        self.assertTrue(all(item.exchange == "Coinbase" for item in snapshot.symbols))

    def test_catalog_rejects_empty_product_metadata(self):
        class Client:
            def product(self, product_id):
                return {"id": "not-the-requested-product", "status": "online"}

        with self.assertRaises(ProviderSyncError):
            CoinbaseCryptoCatalogAdapter(client=Client()).fetch_market()

    def test_historical_pagination_is_bounded_to_300_and_deduplicates(self):
        calls = []

        class Client:
            def candles(self, product_id, start, end, granularity):
                calls.append((product_id, start, end, granularity))
                end = int(end)
                return [
                    candle(end - index * 60, 100 + index, 101 + index, 99 + index, 100.5 + index, 2)
                    for index in range(300)
                ]

        bars = fetch_crypto_historical_bars("BTC-USD", "1分", count=1000, client=Client(), now=datetime.fromtimestamp(2_000_000, tz=timezone.utc))
        self.assertEqual(len(bars), 1000)
        self.assertEqual(bars, sorted(bars, key=lambda row: row["time"]))
        self.assertEqual(len({row["time"] for row in bars}), 1000)
        self.assertLessEqual(len(calls), 32)
        self.assertTrue(all(call[3] == 60 for call in calls))

    def test_empty_historical_source_does_not_fill_fake_bars(self):
        class Client:
            def candles(self, *args, **kwargs):
                return []

        self.assertEqual(fetch_crypto_historical_bars(
            "ETH-USD", "1分", count=1000, client=Client(),
            now=datetime.fromtimestamp(1_700_000_000, tz=timezone.utc),
        ), [])

    def test_non_native_aggregation_uses_utc_buckets_and_preserves_gaps(self):
        rows = [
            {"time": 0, "open": 10, "high": 11, "low": 9, "close": 10.5, "volume": 2, "amount": 77, "turnover_rate": 1},
            {"time": 900, "open": 10.5, "high": 12, "low": 10, "close": 11.5, "volume": 3, "amount": 88, "turnover_rate": 2},
            {"time": 2700, "open": 12, "high": 13, "low": 11, "close": 12.5, "volume": 4, "amount": 99, "turnover_rate": 3},
        ]
        bars = aggregate_crypto_bars(rows, "30分")
        self.assertEqual([bar["time"] for bar in bars], [0, 1800])
        self.assertEqual(bars[0]["open"], 10)
        self.assertEqual(bars[0]["high"], 12)
        self.assertEqual(bars[0]["low"], 9)
        self.assertEqual(bars[0]["close"], 11.5)
        self.assertEqual(bars[0]["volume"], 5)
        self.assertIsNone(bars[0]["amount"])
        self.assertIsNone(bars[0]["turnover_rate"])
        self.assertEqual(aggregate_crypto_bars(rows, "2小时")[0]["time"], 0)
        self.assertEqual(aggregate_crypto_bars(rows, "周线")[0]["time"], -259200)
        month_timestamp = int(datetime(2026, 2, 15, tzinfo=timezone.utc).timestamp())
        month = aggregate_crypto_bars([{**rows[0], "time": month_timestamp}], "月线")
        self.assertEqual(month[0]["time"], int(datetime(2026, 2, 1, tzinfo=timezone.utc).timestamp()))

    def test_quote_does_not_invent_previous_close_change_or_missing_fields(self):
        from .crypto_provider import crypto_quote

        class Client:
            def ticker(self, product_id):
                return {"price": "60000.25", "bid": "60000", "ask": "60001", "volume_24h": "12.5", "time": "2026-09-06T00:00:00Z"}

            def stats(self, product_id):
                return {"open": "59900", "high": "60100", "low": "59000"}

        payload = crypto_quote("BTC-USD", client=Client(), name="Bitcoin")
        self.assertEqual(payload["code"], "CC.BTC-USD")
        self.assertEqual(payload["price"], 60000.25)
        self.assertIsNone(payload["change"])
        self.assertIsNone(payload["previous_close"])
        self.assertEqual(payload["source"], COINBASE_PROVIDER)

    def test_realtime_trade_aggregation_deduplicates_and_respects_boundaries(self):
        provider = CoinbaseRealtimeProvider(client=object())
        received = []
        provider._callbacks[("CC.BTC-USD", "1分")].add(received.append)
        provider._products.add("BTC-USD")
        base = 1_700_000_000
        first_bucket = base - base % 60
        provider._handle_trade({"product_id": "BTC-USD", "trade_id": "a", "price": "100", "size": "1", "time": base}, 1)
        provider._handle_trade({"product_id": "BTC-USD", "trade_id": "b", "price": "95", "size": "2", "time": base + 20}, 2)
        provider._handle_trade({"product_id": "BTC-USD", "trade_id": "b", "price": "95", "size": "2", "time": base + 20}, 3)
        provider._handle_trade({"product_id": "BTC-USD", "trade_id": "late", "price": "80", "size": "5", "time": base - 60}, 4)
        first = provider._bars[("BTC-USD", "1分")]
        provider._handle_trade({"product_id": "BTC-USD", "trade_id": "c", "price": "110", "size": "3", "time": base + 60}, 5)
        self.assertEqual(first.time, first_bucket)
        self.assertEqual(first.open, 100)
        self.assertEqual(first.high, 100)
        self.assertEqual(first.low, 95)
        self.assertEqual(first.close, 95)
        self.assertEqual(first.volume, 3)
        self.assertEqual(provider._bars[("BTC-USD", "1分")].time, first_bucket + 60)
        self.assertEqual(provider._bars[("BTC-USD", "1分")].close, 110)
        self.assertEqual(len(received), 3)

    def test_heartbeat_is_not_a_kline_event_and_sequence_gap_is_reconnecting(self):
        provider = CoinbaseRealtimeProvider(client=object())
        statuses = []
        provider._callbacks[("CC.BTC-USD", "1分")].add(lambda event: statuses.append(event) if isinstance(event, dict) else None)
        connection = type("Connection", (), {"closed": False, "close": lambda self: setattr(self, "closed", True)})()
        provider._handle_message(json.dumps({"channel": "heartbeats", "sequence_num": 0, "events": [{"heartbeat": {}}]}), connection)
        self.assertEqual(statuses, [])
        provider._handle_message(json.dumps({"channel": "subscriptions", "sequence_num": 1, "events": []}), connection)
        provider._handle_message(json.dumps({"channel": "market_trades", "sequence_num": 2, "events": []}), connection)
        provider._handle_message(json.dumps({"channel": "heartbeats", "sequence_num": 3, "events": [{"heartbeat": {}}]}), connection)
        self.assertEqual(statuses, [])
        provider._handle_message(json.dumps({"channel": "market_trades", "sequence_num": 5, "events": []}), connection)
        self.assertTrue(connection.closed)
        self.assertEqual(statuses[-1]["status"], "reconnecting")
        self.assertIn("sequence gap", statuses[-1]["error"])

    def test_reconcile_replays_real_trades_received_during_rest(self):
        provider = None
        bucket = 960

        class Client:
            def candles(self, *args, **kwargs):
                provider._handle_trade({
                    "product_id": "BTC-USD", "trade_id": "during-rest", "price": "102", "size": "2",
                    "time": 1001,
                }, 1)
                return [candle(bucket, 100, 101, 99, 100.5, 10), candle(bucket - 60, 98, 100, 97, 99, 8)]

        provider = CoinbaseRealtimeProvider(client=Client())
        provider._callbacks[("CC.BTC-USD", "1分")].add(lambda event: None)
        with patch("core.crypto_provider.time.time", return_value=1000):
            result = provider.latest_snapshot("CC.BTC-USD", "1分")
        self.assertEqual(result.time, bucket)
        self.assertEqual(result.close, 102)
        self.assertEqual(result.volume, 12)

    def test_product_subscription_refcount_is_shared_across_periods(self):
        provider = CoinbaseRealtimeProvider(client=object())
        with patch.object(provider, "_ensure_thread_locked"), patch.object(provider, "_send") as send:
            provider.subscribe("CC.BTC-USD", "1分", lambda event: None)
            provider.subscribe("CC.BTC-USD", "5分", lambda event: None)
            self.assertEqual(provider._product_refs["BTC-USD"], 2)
            self.assertEqual(provider._products, {"BTC-USD"})
            self.assertEqual(send.call_count, 1)
            provider.unsubscribe("CC.BTC-USD", "1分")
            self.assertEqual(provider._product_refs["BTC-USD"], 1)
            provider.unsubscribe("CC.BTC-USD", "5分")
            self.assertNotIn("BTC-USD", provider._products)

    def test_realtime_provider_has_no_database_tick_write_path(self):
        source = inspect.getsource(CoinbaseRealtimeProvider)
        self.assertNotIn("MarketSymbol.objects", source)
        self.assertNotIn("WatchlistEntry.objects", source)
        self.assertIn("_trade_log", source)


class CryptoCatalogAndApiTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = get_user_model().objects.create_user(
            username="crypto@example.com", email="crypto@example.com", password="safe-password-123"
        )

    def symbol(self, code="CC.BTC-USD", name="Bitcoin"):
        return MarketSymbol.objects.create(
            code=code, name=name, market="crypto", exchange="Coinbase", security_type="CRYPTO_SPOT",
            active=True, provider=COINBASE_PROVIDER, provider_symbol=code[3:],
        )

    def test_coinbase_catalog_scope_does_not_inactivate_futu_symbols(self):
        stock = MarketSymbol.objects.create(
            code="SH.600519", name="测试股票", market="cn", exchange="SH", security_type="STOCK",
            active=True, provider="futu-opend", provider_symbol="SH.600519",
        )
        snapshot = ProviderCatalogSnapshot(
            market="crypto",
            symbols=(ProviderSymbol(
                code="CC.BTC-USD", name="Bitcoin", market="crypto", exchange="Coinbase",
                security_type="CRYPTO_SPOT", active=True, provider=COINBASE_PROVIDER,
                market_cap_currency=None, market_cap_eligible=False, provider_symbol="BTC-USD",
            ),),
            market_caps={}, provider=COINBASE_PROVIDER,
        )
        stats = apply_catalog_snapshot(snapshot)
        self.assertEqual(stats["added"], 1)
        self.assertTrue(MarketSymbol.objects.get(pk=stock.pk).active)
        self.assertEqual(MarketSymbol.objects.get(code="CC.BTC-USD").provider_symbol, "BTC-USD")
        repeat = apply_catalog_snapshot(snapshot)
        self.assertEqual(repeat["added"], 0)
        self.assertEqual(repeat["inactive"], 0)
        with self.assertRaises(ProviderSyncError):
            apply_catalog_snapshot(ProviderCatalogSnapshot(
                market="crypto", symbols=(), market_caps={}, provider=COINBASE_PROVIDER,
            ))
        self.assertTrue(MarketSymbol.objects.get(code="CC.BTC-USD").active)

    def test_crypto_watchlist_search_and_quote_are_provider_backed(self):
        self.symbol()
        self.client.force_login(self.user)
        search = self.client.get("/api/symbols/crypto/?q=BTC&limit=10&page=1")
        self.assertEqual(search.status_code, 200)
        self.assertEqual([item["code"] for item in search.json()["items"]], ["CC.BTC-USD"])
        with patch("core.views.crypto_quote", return_value={
            "code": "CC.BTC-USD", "name": "Bitcoin", "price": 60000,
            "change": None, "previous_close": None, "open": 59000, "high": 61000,
            "low": 58000, "updated_at": "2026-09-06T00:00:00Z", "source": COINBASE_PROVIDER,
            "status": "ready",
        }) as quote:
            response = self.client.get("/api/quote/CC.BTC-USD/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["source"], COINBASE_PROVIDER)
        quote.assert_called_once_with("BTC-USD", client=quote.call_args.kwargs["client"], name="Bitcoin")
        csrf = self.client.get("/api/csrf/").cookies["csrftoken"].value
        response = self.client.post(
            "/api/watchlist/", data=json.dumps({"code": "CC.BTC-USD"}), content_type="application/json",
            HTTP_X_CSRFTOKEN=csrf,
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(WatchlistEntry.objects.filter(user=self.user).count(), 1)

    def test_crypto_kline_routes_coinbase_and_has_no_fake_fill(self):
        self.symbol()
        self.client.force_login(self.user)
        bars = [{"time": 1, "open": 1, "high": 2, "low": 1, "close": 2, "volume": 3, "amount": None, "turnover_rate": None}]
        with patch("core.views.fetch_crypto_historical_bars", return_value=bars) as fetch:
            response = self.client.get("/api/kline/CC.BTC-USD/?period=1分&count=100")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["source"], COINBASE_PROVIDER)
        self.assertEqual(response.json()["bars"], bars)
        fetch.assert_called_once()
        self.assertEqual(fetch.call_args.args[0], "BTC-USD")

    def test_crypto_realtime_router_selects_coinbase_without_creating_second_registry(self):
        futu = type("Futu", (), {"provider_name": "futu-opend"})()
        crypto = type("Crypto", (), {"provider_name": COINBASE_PROVIDER})()
        router = MarketDataProviderRouter(futu, crypto)
        self.assertIs(router.provider_for("CC.BTC-USD"), crypto)
        self.assertIs(router.provider_for("SH.600519"), futu)
        self.assertEqual(router.provider_name_for("CC.ETH-USD"), COINBASE_PROVIDER)
