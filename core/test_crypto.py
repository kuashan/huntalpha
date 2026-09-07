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
    MAX_SEEN_TRADE_IDS,
)
from .models import MarketSymbol, WatchlistEntry
from .realtime.router import MarketDataProviderRouter
from .realtime.registry import RealtimeRegistry
from .realtime.contracts import NormalizedBar
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

    def test_quote_uses_real_coinbase_volume_and_24h_change_without_previous_close(self):
        from .crypto_provider import crypto_quote

        class Client:
            def ticker(self, product_id):
                return {"price": "60000.25", "bid": "60000", "ask": "60001", "volume": "12.5", "time": "2026-09-06T00:00:00Z"}

            def stats(self, product_id):
                return {"open": "59900", "high": "60100", "low": "59000"}

        payload = crypto_quote("BTC-USD", client=Client(), name="Bitcoin")
        self.assertEqual(payload["code"], "CC.BTC-USD")
        self.assertEqual(payload["price"], 60000.25)
        self.assertAlmostEqual(payload["change"], (60000.25 - 59900) / 59900 * 100)
        self.assertIsNone(payload["previous_close"])
        self.assertEqual(payload["volume"], 12.5)
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

    def test_connection_sequence_accepts_heartbeat_interleaving(self):
        provider = CoinbaseRealtimeProvider(client=object())
        connection = type("Connection", (), {"closed": False, "close": lambda self: setattr(self, "closed", True)})()
        provider._ws = connection
        provider._connection_generation = 1
        trade = lambda product, trade_id: {"product_id": product, "trade_id": trade_id, "price": "100", "size": "1", "time": 1000}
        provider._handle_message(json.dumps({"channel": "market_trades", "sequence_num": 4, "events": [{"type": "update", "trades": [trade("BTC-USD", "btc-4")]}]}), connection)
        provider._handle_message(json.dumps({"channel": "heartbeats", "sequence_num": 5, "events": [{"heartbeat": {"heartbeat_counter": "1"}}]}), connection)
        provider._handle_message(json.dumps({"channel": "market_trades", "sequence_num": 6, "events": [{"type": "update", "trades": [trade("BTC-USD", "btc-6")]}]}), connection)
        self.assertEqual(provider._last_sequence, 6)
        self.assertEqual(provider._last_heartbeat_counter, "1")
        self.assertFalse(connection.closed)

    def test_connection_sequence_accepts_interleaved_products_and_heartbeat(self):
        provider = CoinbaseRealtimeProvider(client=object())
        connection = type("Connection", (), {"closed": False, "close": lambda self: setattr(self, "closed", True)})()
        provider._ws = connection
        provider._connection_generation = 1
        trade = lambda product, trade_id: {"product_id": product, "trade_id": trade_id, "price": "100", "size": "1", "time": 1000}
        provider._handle_message(json.dumps({"channel": "market_trades", "sequence_num": 10, "events": [{"type": "update", "trades": [trade("BTC-USD", "btc-10")]}]}), connection)
        provider._handle_message(json.dumps({"channel": "market_trades", "sequence_num": 11, "events": [{"type": "update", "trades": [trade("ETH-USD", "eth-11")]}]}), connection)
        provider._handle_message(json.dumps({"channel": "heartbeats", "sequence_num": 12, "events": [{"heartbeat": {"heartbeat_counter": "2"}}]}), connection)
        provider._handle_message(json.dumps({"channel": "market_trades", "sequence_num": 13, "events": [{"type": "update", "trades": [trade("BTC-USD", "btc-13")]}]}), connection)
        self.assertEqual(provider._last_sequence, 13)
        self.assertEqual(provider._last_heartbeat_counter, "2")
        self.assertFalse(connection.closed)

    def test_connection_sequence_gap_reconnects(self):
        provider = CoinbaseRealtimeProvider(client=object())
        connection = type("Connection", (), {"closed": False, "close": lambda self: setattr(self, "closed", True)})()
        provider._ws = connection
        provider._connection_generation = 1
        trade = lambda trade_id: {"product_id": "BTC-USD", "trade_id": trade_id, "price": "100", "size": "1", "time": 1000}
        provider._handle_message(json.dumps({"channel": "market_trades", "sequence_num": 4, "events": [{"type": "update", "trades": [trade("a")]}]}), connection)
        provider._handle_message(json.dumps({"channel": "market_trades", "sequence_num": 7, "events": [{"type": "update", "trades": [trade("gap")]}]}), connection)
        self.assertTrue(connection.closed)
        self.assertEqual(provider.status, "reconnecting")
        self.assertNotIn("gap", provider._seen_ids["BTC-USD"])

    def test_stale_and_duplicate_connection_sequences_are_ignored(self):
        provider = CoinbaseRealtimeProvider(client=object())
        connection = type("Connection", (), {"closed": False, "close": lambda self: setattr(self, "closed", True)})()
        provider._ws = connection
        provider._connection_generation = 1
        trade = lambda trade_id: {"product_id": "BTC-USD", "trade_id": trade_id, "price": "100", "size": "1", "time": 1000}
        provider._handle_message(json.dumps({"channel": "market_trades", "sequence_num": 5, "events": [{"type": "update", "trades": [trade("a")]}]}), connection)
        provider._handle_message(json.dumps({"channel": "market_trades", "sequence_num": 5, "events": [{"type": "update", "trades": [trade("duplicate")]}]}), connection)
        provider._handle_message(json.dumps({"channel": "heartbeats", "sequence_num": 4, "events": [{"heartbeat": {"heartbeat_counter": "1"}}]}), connection)
        self.assertEqual(provider._last_sequence, 5)
        self.assertFalse(connection.closed)
        self.assertNotIn("duplicate", provider._seen_ids["BTC-USD"])

    def test_new_connection_generation_resets_sequence_baseline(self):
        provider = CoinbaseRealtimeProvider(client=object())
        old_connection = type("Connection", (), {"closed": False, "close": lambda self: setattr(self, "closed", True)})()
        new_connection = type("Connection", (), {"closed": False, "close": lambda self: setattr(self, "closed", True)})()
        provider._ws = old_connection
        provider._connection_generation = 1
        provider._handle_message(json.dumps({"channel": "heartbeats", "sequence_num": 99, "events": [{"heartbeat": {"heartbeat_counter": "1"}}]}), old_connection)
        provider._ws = new_connection
        provider._connection_generation = 2
        provider._last_sequence = None
        provider._handle_message(json.dumps({"channel": "heartbeats", "sequence_num": 1, "events": [{"heartbeat": {"heartbeat_counter": "2"}}]}), new_connection)
        self.assertEqual(provider._last_sequence, 1)
        self.assertFalse(new_connection.closed)

    def test_old_generation_message_cannot_change_current_sequence(self):
        provider = CoinbaseRealtimeProvider(client=object())
        old_connection = type("Connection", (), {"closed": False, "close": lambda self: setattr(self, "closed", True)})()
        new_connection = type("Connection", (), {"closed": False, "close": lambda self: setattr(self, "closed", True)})()
        provider._ws = new_connection
        provider._connection_generation = 2
        provider._last_sequence = 1
        trade = {"product_id": "BTC-USD", "trade_id": "old", "price": "100", "size": "1", "time": 1000}
        provider._handle_message(json.dumps({"channel": "market_trades", "sequence_num": 2, "events": [{"type": "update", "trades": [trade]}]}), old_connection)
        self.assertEqual(provider._last_sequence, 1)
        self.assertNotIn("old", provider._seen_ids["BTC-USD"])
        self.assertFalse(new_connection.closed)

    def test_reconcile_prefers_authoritative_volume_for_overlapping_trades(self):
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
        self.assertEqual(result.close, 100.5)
        self.assertEqual(result.volume, 10)

    def test_reconcile_gate_stays_held_through_authoritative_commit(self):
        gate_seen_during_commit = []

        class Client:
            def candles(self, *args, **kwargs):
                return [candle(960, 100, 101, 99, 100.5, 10)]

        provider = CoinbaseRealtimeProvider(client=Client())

        class ObservingBars(dict):
            def __setitem__(self, key, value):
                gate_seen_during_commit.append(key in provider._reconcile_in_progress)
                return super().__setitem__(key, value)

        provider._bars = ObservingBars()
        provider.latest_snapshot("CC.BTC-USD", "1分")
        self.assertEqual(gate_seen_during_commit, [True])
        self.assertNotIn(("BTC-USD", "1分"), provider._reconcile_in_progress)

    def test_trade_cannot_slip_into_single_key_reconcile_commit(self):
        gate_seen_during_commit = []

        class Client:
            def candles(self, *args, **kwargs):
                return [candle(960, 100, 101, 99, 100.5, 10)]

        provider = CoinbaseRealtimeProvider(client=Client())

        class ObservingBars(dict):
            def __setitem__(self, key, value):
                gate_seen_during_commit.append(key in provider._reconcile_in_progress)
                provider._handle_trade({
                    "product_id": "BTC-USD", "trade_id": "during-commit", "price": "102", "size": "2",
                    "time": 1001,
                }, 1)
                return super().__setitem__(key, value)

        provider._bars = ObservingBars()
        provider.latest_snapshot("CC.BTC-USD", "1分")
        self.assertEqual(gate_seen_during_commit, [True])
        self.assertEqual(provider._bars[("BTC-USD", "1分")].close, 100.5)
        self.assertNotIn(("BTC-USD", "1分"), provider._reconcile_in_progress)

    def test_product_subscription_refcount_is_shared_across_periods(self):
        provider = CoinbaseRealtimeProvider(client=object())
        with patch.object(provider, "_ensure_thread_locked"):
            provider.subscribe("CC.BTC-USD", "1分", lambda event: None)
            provider.subscribe("CC.BTC-USD", "5分", lambda event: None)
            self.assertEqual(provider._product_refs["BTC-USD"], 2)
            self.assertEqual(provider._products, {"BTC-USD"})
            self.assertEqual(provider._products, {"BTC-USD"})
            provider.unsubscribe("CC.BTC-USD", "1分")
            self.assertEqual(provider._product_refs["BTC-USD"], 1)
            provider.unsubscribe("CC.BTC-USD", "5分")
            self.assertNotIn("BTC-USD", provider._products)

    def test_realtime_provider_has_no_database_tick_write_path(self):
        source = inspect.getsource(CoinbaseRealtimeProvider)
        self.assertNotIn("MarketSymbol.objects", source)
        self.assertNotIn("WatchlistEntry.objects", source)
        self.assertIn("_seen_order", source)

    def test_snapshot_seeds_trade_ids_without_changing_ohlcv(self):
        provider = CoinbaseRealtimeProvider(client=object())
        provider._callbacks[("CC.BTC-USD", "1分")].add(lambda event: None)
        from .realtime.contracts import NormalizedBar
        provider._bars[("BTC-USD", "1分")] = NormalizedBar(
            provider=COINBASE_PROVIDER, market="crypto", symbol="CC.BTC-USD", period="1分", time=960,
            open=100, high=101, low=99, close=100, volume=10, sequence=10, event_kind="reconcile",
        )
        snapshot = {"channel": "market_trades", "sequence_num": 10, "events": [{"type": "snapshot", "trades": [{"product_id": "BTC-USD", "trade_id": "seed", "price": "100", "size": "4", "time": 1000}]}]}
        provider._handle_message(json.dumps(snapshot))
        self.assertEqual(provider._bars[("BTC-USD", "1分")].volume, 10)
        self.assertIn("seed", provider._seen_ids["BTC-USD"])

    def test_update_drives_ohlcv_after_snapshot(self):
        provider = CoinbaseRealtimeProvider(client=object())
        provider._callbacks[("CC.BTC-USD", "1分")].add(lambda event: None)
        from .realtime.contracts import NormalizedBar
        provider._bars[("BTC-USD", "1分")] = NormalizedBar(
            provider=COINBASE_PROVIDER, market="crypto", symbol="CC.BTC-USD", period="1分", time=960,
            open=100, high=101, low=99, close=100, volume=10, event_kind="reconcile",
        )
        provider._handle_message(json.dumps({"channel": "market_trades", "sequence_num": 10, "events": [{"type": "snapshot", "trades": [{"product_id": "BTC-USD", "trade_id": "seed", "price": "100", "size": "4", "time": 1000}]}]}))
        provider._handle_message(json.dumps({"channel": "market_trades", "sequence_num": 11, "events": [{"type": "update", "trades": [{"product_id": "BTC-USD", "trade_id": "live", "price": "102", "size": "2", "time": 1010}]}]}))
        self.assertEqual(provider._bars[("BTC-USD", "1分")].close, 102)
        self.assertEqual(provider._bars[("BTC-USD", "1分")].volume, 12)

    def test_bounded_trade_ids_evict_the_oldest_consistently(self):
        provider = CoinbaseRealtimeProvider(client=object())
        for index in range(MAX_SEEN_TRADE_IDS + 100):
            provider._remember_trade_id("BTC-USD", f"trade-{index}")
        self.assertEqual(len(provider._seen_ids["BTC-USD"]), MAX_SEEN_TRADE_IDS)
        self.assertEqual(len(provider._seen_order["BTC-USD"]), MAX_SEEN_TRADE_IDS)
        self.assertEqual(provider._seen_ids["BTC-USD"], set(provider._seen_order["BTC-USD"]))
        self.assertNotIn("trade-0", provider._seen_ids["BTC-USD"])
        self.assertFalse(provider._remember_trade_id("BTC-USD", f"trade-{MAX_SEEN_TRADE_IDS + 99}"))
        self.assertTrue(provider._remember_trade_id("BTC-USD", "trade-0"))

    def test_heartbeat_timeout_closes_stale_connection_once(self):
        provider = CoinbaseRealtimeProvider(client=object())
        connection = type("Connection", (), {"closed": False, "close": lambda self: setattr(self, "closed", True)})()
        provider._products.add("BTC-USD")
        provider._ws = connection
        provider._thread = __import__("threading").current_thread()
        provider._connection_generation = 3
        provider._last_heartbeat_monotonic = time.monotonic() - provider.HEARTBEAT_TIMEOUT_SECONDS - 1
        self.assertEqual(provider.health_check(), "reconnecting")
        self.assertTrue(connection.closed)
        self.assertEqual(provider.health_check(), "reconnecting")

    def test_dynamic_subscription_sync_reaches_the_current_connection(self):
        class Connection:
            def __init__(self):
                self.messages = []
                self.closed = False

            def send(self, message):
                self.messages.append(json.loads(message))

            def close(self):
                self.closed = True

        provider = CoinbaseRealtimeProvider(client=object())
        connection = Connection()
        provider._ws = connection
        provider._connection_generation = 1
        provider._products = {"BTC-USD"}
        provider._sync_subscriptions()
        provider._products.add("ETH-USD")
        provider._sync_subscriptions()
        self.assertEqual([message["product_ids"] for message in connection.messages], [["BTC-USD"], ["ETH-USD"]])
        self.assertEqual(provider._connection_products, {"BTC-USD", "ETH-USD"})

    def test_subscription_send_failure_is_not_marked_successful(self):
        class Connection:
            closed = False

            def send(self, message):
                raise OSError("socket closed")

            def close(self):
                self.closed = True

        provider = CoinbaseRealtimeProvider(client=object())
        connection = Connection()
        provider._ws = connection
        provider._connection_generation = 4
        provider._products = {"BTC-USD"}
        provider._sync_subscriptions()
        self.assertEqual(provider._connection_products, set())
        self.assertTrue(connection.closed)
        self.assertEqual(provider.status, "reconnecting")

    def test_authoritative_reconcile_is_published_through_registry_state_store(self):
        class Client:
            def __init__(self):
                self.volume = 10

            def candles(self, *args, **kwargs):
                return [candle(960, 100, 101, 99, 100.5, self.volume)]

        client = Client()
        provider = CoinbaseRealtimeProvider(client=client)
        registry = RealtimeRegistry(provider, grace_seconds=0.01)
        with patch.object(provider, "_ensure_thread_locked"):
            consumer = registry.subscribe("CC.BTC-USD", "1分")
        key = registry.key_for("CC.BTC-USD", "1分")
        self.assertEqual(registry.state_store.capture(key).current_bar.volume, 10)
        client.volume = 18
        provider._reconcile_active()
        corrected = registry.state_store.capture(key).current_bar
        self.assertEqual(corrected.volume, 18)
        self.assertEqual(corrected.event_kind, "reconcile")
        events = []
        while not consumer.events.empty():
            events.append(consumer.events.get())
        self.assertTrue(any(event.get("bar", {}).get("volume") == 18 for event in events))
        registry.close()


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
