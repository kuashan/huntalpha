"""Coinbase public market-data adapters for the first crypto products.

This module contains no credentials and never manufactures a quote or bar.  The
catalog is intentionally limited to the two products approved for the first
crypto release; every name, status, quote, candle, and trade comes from
Coinbase's public APIs.
"""

from collections import defaultdict, deque
from datetime import datetime, timezone
import json
import threading
import time
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

try:
    import websocket
except ImportError:  # pragma: no cover - exercised by deployment checks
    websocket = None

from .realtime.contracts import NormalizedBar, optional_numeric
from .realtime.provider import REALTIME_PERIOD_SUBTYPES, RealtimeMarketProvider, RealtimeProviderError
from .symbol_catalog import COINBASE_PROVIDER, ProviderCatalogSnapshot, ProviderSymbol, ProviderSyncError


COINBASE_REST_BASE = "https://api.exchange.coinbase.com"
COINBASE_WS_URL = "wss://advanced-trade-ws.coinbase.com"
CRYPTO_PRODUCTS = ("BTC-USD", "ETH-USD")
CRYPTO_PERIODS = ("1分", "5分", "15分", "30分", "60分", "2小时", "4小时", "日线", "周线", "月线")
NATIVE_GRANULARITIES = {"1分": 60, "5分": 300, "15分": 900, "60分": 3600, "日线": 86400}
SOURCE_PERIODS = {"30分": "15分", "2小时": "60分", "4小时": "60分", "周线": "日线", "月线": "日线"}
MAX_CANDLE_REQUESTS = 32
MAX_CANDLES_PER_REQUEST = 300
MAX_SEEN_TRADE_IDS = 5000


def provider_symbol_for(code):
    normalized = str(code or "").strip().upper()
    if normalized.startswith("CC."):
        return normalized[3:]
    return normalized


def internal_symbol_for(product_id):
    return f"CC.{str(product_id).strip().upper()}"


def _finite(value, positive=False):
    number = optional_numeric(value)
    if number is None or (positive and number <= 0):
        return None
    return number


def _timestamp(value):
    if isinstance(value, (int, float)):
        return int(value)
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return int(parsed.astimezone(timezone.utc).timestamp())


def _product_id(value):
    product = str(value or "").strip().upper()
    return product if product in CRYPTO_PRODUCTS else None


class CoinbaseApiError(RealtimeProviderError):
    pass


class CoinbasePublicClient:
    """Small credential-free Coinbase Exchange REST client."""

    def __init__(self, request_json=None, base_url=COINBASE_REST_BASE, timeout=10):
        self.request_json = request_json or self._request_json
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def _request_json(self, url):
        request = Request(url, headers={"Accept": "application/json", "User-Agent": "HuntAlpha/1.0"})
        try:
            with urlopen(request, timeout=self.timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except Exception as exc:
            raise CoinbaseApiError(f"Coinbase REST unavailable: {exc}") from exc

    def get(self, path, params=None):
        query = f"?{urlencode(params)}" if params else ""
        return self.request_json(f"{self.base_url}{path}{query}")

    def product(self, product_id):
        return self.get(f"/products/{quote(product_id, safe='')}")

    def ticker(self, product_id):
        return self.get(f"/products/{quote(product_id, safe='')}/ticker")

    def stats(self, product_id):
        return self.get(f"/products/{quote(product_id, safe='')}/stats")

    def candles(self, product_id, start, end, granularity):
        return self.get(
            f"/products/{quote(product_id, safe='')}/candles",
            {"start": str(int(start)), "end": str(int(end)), "granularity": str(int(granularity))},
        )


class CoinbaseCryptoCatalogAdapter:
    """Fetch the approved crypto products from Coinbase product metadata."""

    def __init__(self, client=None, products=CRYPTO_PRODUCTS):
        self.client = client or CoinbasePublicClient()
        self.products = tuple(products)

    def fetch_market(self, market="crypto"):
        if market != "crypto":
            raise ProviderSyncError("unsupported_market")
        symbols = []
        for product_id in self.products:
            metadata = self.client.product(product_id)
            actual = _product_id(metadata.get("id") or product_id) if isinstance(metadata, dict) else None
            if actual != product_id:
                raise ProviderSyncError("invalid_product_metadata")
            status = str(metadata.get("status") or "").lower()
            name = str(metadata.get("display_name") or metadata.get("base_currency") or product_id).strip()
            symbols.append(ProviderSymbol(
                code=internal_symbol_for(product_id),
                name=name,
                market="crypto",
                exchange="Coinbase",
                security_type="CRYPTO_SPOT",
                active=status in {"", "online"},
                provider=COINBASE_PROVIDER,
                market_cap_currency=None,
                market_cap_eligible=False,
                provider_symbol=product_id,
            ))
        if not symbols:
            raise ProviderSyncError("suspicious_empty_catalog")
        return ProviderCatalogSnapshot(
            market="crypto", symbols=tuple(symbols), market_caps={}, provider=COINBASE_PROVIDER,
        )


def _parse_candle(row):
    if not isinstance(row, (list, tuple)) or len(row) < 6:
        return None
    try:
        timestamp = int(float(row[0]))
    except (TypeError, ValueError):
        return None
    values = [_finite(value) for value in (row[3], row[2], row[1], row[4])]
    if any(value is None for value in values):
        return None
    return {
        "time": timestamp,
        "open": values[0],
        "high": values[1],
        "low": values[2],
        "close": values[3],
        "volume": _finite(row[5]),
        "amount": None,
        "turnover_rate": None,
    }


def _dedupe_bars(rows):
    return sorted({row["time"]: row for row in rows if row and row.get("time") is not None}.values(), key=lambda row: row["time"])


def _source_count(period, count):
    if period == "30分":
        return count * 2 + 2
    if period in {"2小时", "4小时"}:
        return count * (2 if period == "2小时" else 4) + 2
    if period == "周线":
        return count * 7 + 2
    if period == "月线":
        return count * 31 + 2
    return count + 2


def _bucket_start(timestamp, period):
    dt = datetime.fromtimestamp(int(timestamp), tz=timezone.utc)
    if period == "周线":
        return int(datetime(dt.year, dt.month, dt.day, tzinfo=timezone.utc).timestamp()) - dt.weekday() * 86400
    if period == "月线":
        return int(datetime(dt.year, dt.month, 1, tzinfo=timezone.utc).timestamp())
    seconds = {
        "1分": 60, "5分": 300, "15分": 900, "30分": 1800,
        "60分": 3600, "2小时": 7200, "4小时": 14400, "日线": 86400,
    }.get(period)
    if seconds is None:
        raise CoinbaseApiError(f"unsupported crypto period: {period}")
    return int(timestamp) - int(timestamp) % seconds


def aggregate_crypto_bars(rows, period, count=None):
    """Aggregate only real source bars and preserve missing intervals as gaps."""
    if period in NATIVE_GRANULARITIES:
        result = _dedupe_bars(rows)
    else:
        buckets = {}
        for row in _dedupe_bars(rows):
            bucket = _bucket_start(row["time"], period)
            current = buckets.get(bucket)
            if current is None:
                buckets[bucket] = {
                    **row,
                    "time": bucket,
                    "open": row["open"],
                    "high": row["high"],
                    "low": row["low"],
                    "close": row["close"],
                    "volume": row["volume"],
                    "amount": None,
                    "turnover_rate": None,
                }
                continue
            current["high"] = max(current["high"], row["high"])
            current["low"] = min(current["low"], row["low"])
            current["close"] = row["close"]
            if current["volume"] is None or row["volume"] is None:
                current["volume"] = None
            else:
                current["volume"] += row["volume"]
        result = [buckets[key] for key in sorted(buckets)]
    return result[-count:] if count is not None else result


def fetch_crypto_historical_bars(product_id, period, count=1000, client=None, now=None, before=None):
    product_id = _product_id(product_id)
    if product_id is None or period not in CRYPTO_PERIODS:
        raise CoinbaseApiError("unsupported crypto product or period")
    client = client or CoinbasePublicClient()
    source_period = period if period in NATIVE_GRANULARITIES else SOURCE_PERIODS[period]
    granularity = NATIVE_GRANULARITIES[source_period]
    target = min(max(int(count), 1), 1000)
    needed = _source_count(period, target)
    end = int(before or (now or datetime.now(timezone.utc)).timestamp())
    rows = []
    pages = 0
    seen_pages = set()
    cutoff = int(before) if before is not None else None
    while len(rows) < needed and pages < MAX_CANDLE_REQUESTS:
        page_end = end
        page_start = max(0, page_end - granularity * MAX_CANDLES_PER_REQUEST)
        payload = client.candles(product_id, page_start, page_end, granularity)
        if not isinstance(payload, list):
            raise CoinbaseApiError("Coinbase candles returned invalid payload")
        page = _dedupe_bars([_parse_candle(row) for row in payload])
        if cutoff is not None:
            page = [row for row in page if row["time"] < cutoff]
        signature = tuple(row["time"] for row in page)
        if not page or signature in seen_pages:
            break
        seen_pages.add(signature)
        rows.extend(page)
        oldest = min(row["time"] for row in page)
        if oldest >= page_end:
            break
        end = oldest
        pages += 1
    return aggregate_crypto_bars(rows, period, target)


def crypto_quote(product_id, client=None, name=None):
    product_id = _product_id(product_id)
    if product_id is None:
        raise CoinbaseApiError("unsupported crypto product")
    client = client or CoinbasePublicClient()
    ticker = client.ticker(product_id)
    stats = client.stats(product_id)
    price = _finite(ticker.get("price"), positive=True)
    if price is None:
        raise CoinbaseApiError("Coinbase ticker has no valid price")
    stats = stats if isinstance(stats, dict) else {}
    return {
        "code": internal_symbol_for(product_id),
        "name": name or product_id,
        "price": price,
        "change": None,
        "previous_close": None,
        "best_bid": _finite(ticker.get("bid"), positive=True),
        "best_ask": _finite(ticker.get("ask"), positive=True),
        "volume": _finite(ticker.get("volume_24h")),
        "open": _finite(stats.get("open")),
        "high": _finite(stats.get("high")),
        "low": _finite(stats.get("low")),
        "updated_at": ticker.get("time"),
        "source": COINBASE_PROVIDER,
        "status": "ready",
    }


def _message_time(value):
    return _timestamp(value) or int(time.time())


class CoinbaseRealtimeProvider(RealtimeMarketProvider):
    """One public Coinbase WebSocket shared by all crypto products/periods."""

    provider_name = COINBASE_PROVIDER

    def __init__(self, client=None, websocket_factory=None, reconnect_delay=1.0):
        self.client = client or CoinbasePublicClient()
        self.websocket_factory = websocket_factory or self._create_websocket
        self.reconnect_delay = reconnect_delay
        self._lock = threading.RLock()
        self._callbacks = defaultdict(set)
        self._product_refs = defaultdict(int)
        self._products = set()
        self._bars = {}
        self._seen_ids = defaultdict(set)
        self._seen_order = defaultdict(lambda: deque(maxlen=MAX_SEEN_TRADE_IDS))
        self._trade_log = defaultdict(lambda: deque(maxlen=MAX_SEEN_TRADE_IDS))
        self._last_sequence = None
        self._ws = None
        self._thread = None
        self._stop = threading.Event()
        self._status = "unavailable"
        self._has_connected = False

    @property
    def status(self):
        with self._lock:
            return self._status

    def _create_websocket(self):
        if websocket is None:
            raise RealtimeProviderError("websocket-client dependency is not installed")
        return websocket.create_connection(COINBASE_WS_URL, timeout=10, enable_multithread=True)

    def _key(self, symbol, period):
        product = _product_id(provider_symbol_for(symbol))
        if product is None or period not in REALTIME_PERIOD_SUBTYPES:
            raise RealtimeProviderError(f"unsupported Coinbase subscription: {symbol}/{period}")
        return internal_symbol_for(product), product, period

    def _send(self, payload):
        with self._lock:
            connection = self._ws
        if connection is None:
            return False
        try:
            connection.send(json.dumps(payload))
            return True
        except Exception:
            return False

    def _subscription(self, product_ids):
        return {"type": "subscribe", "product_ids": sorted(product_ids), "channel": "market_trades"}

    def _unsubscribe(self, product_ids):
        return {"type": "unsubscribe", "product_ids": sorted(product_ids), "channel": "market_trades"}

    def _ensure_thread_locked(self):
        if self._thread and self._thread.is_alive():
            self._stop.clear()
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="huntalpha-coinbase-ws", daemon=True)
        self._thread.start()

    def subscribe(self, symbol, period, callback):
        internal, product, normalized_period = self._key(symbol, period)
        with self._lock:
            key = (internal, normalized_period)
            first_key = not self._callbacks[key]
            self._callbacks[key].add(callback)
            if first_key:
                self._product_refs[product] += 1
                first_product = product not in self._products
                self._products.add(product)
            else:
                first_product = False
            self._ensure_thread_locked()
        if first_product:
            self._send(self._subscription([product]))

    def unsubscribe(self, symbol, period):
        internal, product, normalized_period = self._key(symbol, period)
        stop = False
        with self._lock:
            key = (internal, normalized_period)
            if not self._callbacks.pop(key, None):
                return
            self._product_refs[product] -= 1
            if self._product_refs[product] <= 0:
                self._product_refs.pop(product, None)
                self._products.discard(product)
                self._send(self._unsubscribe([product]))
            stop = not self._products
            if stop:
                self._stop.set()
                connection = self._ws
            else:
                connection = None
        if connection is not None:
            try:
                connection.close()
            except Exception:
                pass

    def _reconcile_snapshot(self, product, normalized_period):
        started_at = int(time.time())
        bars = fetch_crypto_historical_bars(product, normalized_period, count=2, client=self.client)
        if not bars:
            raise CoinbaseApiError(f"Coinbase returned no historical bars for {product}")
        source = bars[-1]
        internal = internal_symbol_for(product)
        authoritative = NormalizedBar(
            provider=COINBASE_PROVIDER,
            market="crypto",
            symbol=internal,
            period=normalized_period,
            time=source["time"],
            open=source["open"], high=source["high"], low=source["low"], close=source["close"],
            volume=source["volume"], amount=None, turnover_rate=None,
            is_closed=False, provider_timestamp=int(time.time()), sequence=None,
            mode="streaming", event_kind="reconcile",
        )
        with self._lock:
            self._bars[(product, normalized_period)] = authoritative
            replay = [trade for trade in self._trade_log[product] if trade[0] >= started_at]
        # Trades received while REST was in flight are newer than the
        # authoritative snapshot and must be replayed once, otherwise the
        # bootstrap/reconnect window would silently lose them.
        for _received_at, timestamp, price, size, sequence in replay:
            self._aggregate_trade(product, internal, normalized_period, timestamp, price, size, sequence)
        with self._lock:
            return self._bars[(product, normalized_period)]

    def _reconcile_active(self):
        with self._lock:
            keys = list(self._callbacks)
        for internal, period in keys:
            self._reconcile_snapshot(provider_symbol_for(internal), period)

    def latest_snapshot(self, symbol, period):
        internal, product, normalized_period = self._key(symbol, period)
        return self._reconcile_snapshot(product, normalized_period)

    def _emit_status(self, status, error=None):
        with self._lock:
            self._status = status
            callbacks = [((symbol, period), list(items)) for (symbol, period), items in self._callbacks.items()]
        for (symbol, period), listeners in callbacks:
            payload = {"status": status, "source": COINBASE_PROVIDER, "symbol": symbol, "period": period}
            if error:
                payload["error"] = str(error)
            for callback in listeners:
                callback(payload)

    def _run(self):
        delay = self.reconnect_delay
        while not self._stop.is_set():
            with self._lock:
                products = set(self._products)
            if not products:
                break
            connection = None
            try:
                connection = self.websocket_factory()
                with self._lock:
                    if self._stop.is_set():
                        connection.close()
                        break
                    self._ws = connection
                    self._last_sequence = None
                connection.send(json.dumps(self._subscription(products)))
                connection.send(json.dumps({"type": "subscribe", "channel": "heartbeats"}))
                with self._lock:
                    reconnect = self._has_connected
                if reconnect:
                    self._reconcile_active()
                with self._lock:
                    self._has_connected = True
                self._emit_status("live")
                delay = self.reconnect_delay
                while not self._stop.is_set():
                    try:
                        raw = connection.recv()
                    except Exception as exc:
                        if websocket is not None and isinstance(exc, getattr(websocket, "WebSocketTimeoutException", ())):
                            continue
                        raise
                    if not raw:
                        raise CoinbaseApiError("Coinbase WebSocket closed")
                    self._handle_message(raw, connection)
            except Exception as exc:
                if not self._stop.is_set():
                    self._emit_status("reconnecting", exc)
                    self._stop.wait(delay)
                    delay = min(delay * 2, 15)
            finally:
                with self._lock:
                    if self._ws is connection:
                        self._ws = None
                if connection is not None:
                    try:
                        connection.close()
                    except Exception:
                        pass

    def _handle_message(self, raw, connection=None):
        try:
            payload = json.loads(raw) if isinstance(raw, str) else raw
        except (TypeError, ValueError):
            return
        channel = payload.get("channel") if isinstance(payload, dict) else None
        sequence = payload.get("sequence_num")
        if sequence is not None:
            try:
                sequence = int(sequence)
            except (TypeError, ValueError):
                sequence = None
        if sequence is not None:
            with self._lock:
                previous = self._last_sequence
                if previous is not None and sequence <= previous:
                    return
                self._last_sequence = sequence
            if previous is not None and sequence > previous + 1:
                self._emit_status("reconnecting", "Coinbase market-trades sequence gap")
                try:
                    if connection is not None:
                        connection.close()
                except Exception:
                    pass
                return
        if channel == "heartbeats":
            return
        if channel != "market_trades":
            return
        for event in payload.get("events", []):
            for trade in event.get("trades", []):
                self._handle_trade(trade, sequence)

    def _handle_trade(self, trade, sequence):
        product = _product_id(trade.get("product_id"))
        trade_id = str(trade.get("trade_id") or "").strip()
        price = _finite(trade.get("price"), positive=True)
        size = _finite(trade.get("size"), positive=True)
        timestamp = _timestamp(trade.get("time"))
        if not product or not trade_id or price is None or size is None or timestamp is None:
            return
        with self._lock:
            if trade_id in self._seen_ids[product]:
                return
            self._seen_ids[product].add(trade_id)
            self._seen_order[product].append(trade_id)
            self._trade_log[product].append((int(time.time()), timestamp, price, size, sequence))
            while len(self._seen_ids[product]) > len(self._seen_order[product]):
                self._seen_ids[product].discard(self._seen_order[product][0])
            keys = [key for key in self._callbacks if key[0] == internal_symbol_for(product)]
        for internal, period in keys:
            self._aggregate_trade(product, internal, period, timestamp, price, size, sequence)

    def _aggregate_trade(self, product, internal, period, timestamp, price, size, sequence):
        bucket = _bucket_start(timestamp, period)
        key = (product, period)
        with self._lock:
            existing = self._bars.get(key)
            if existing is not None and bucket < existing.time:
                return
            if existing is not None and bucket == existing.time:
                high_values = [value for value in (existing.high, price) if value is not None]
                low_values = [value for value in (existing.low, price) if value is not None]
                bar = NormalizedBar(
                    **{**existing.__dict__, "high": max(high_values) if high_values else None,
                       "low": min(low_values) if low_values else None, "close": price,
                       "volume": (existing.volume + size) if existing.volume is not None else size,
                       "provider_timestamp": timestamp, "sequence": sequence, "event_kind": "live"}
                )
            else:
                bar = NormalizedBar(
                    provider=COINBASE_PROVIDER, market="crypto", symbol=internal, period=period, time=bucket,
                    open=price, high=price, low=price, close=price, volume=size, amount=None,
                    turnover_rate=None, is_closed=False, provider_timestamp=timestamp, sequence=sequence,
                    mode="streaming", event_kind="live",
                )
            self._bars[key] = bar
            callbacks = list(self._callbacks.get((internal, period), set()))
        for callback in callbacks:
            callback(bar)

    def health_check(self):
        with self._lock:
            if not self._products:
                return self._status
            alive = self._thread is not None and self._thread.is_alive() and self._ws is not None
        return "live" if alive else "reconnecting"

    def close(self):
        self._stop.set()
        with self._lock:
            connection = self._ws
            self._ws = None
            self._callbacks.clear()
            self._products.clear()
            self._product_refs.clear()
            self._status = "unavailable"
        if connection is not None:
            try:
                connection.close()
            except Exception:
                pass
