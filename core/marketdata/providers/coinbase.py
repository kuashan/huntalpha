from __future__ import annotations

from ...crypto_provider import CoinbaseCryptoCatalogAdapter, CoinbasePublicClient, CoinbaseRealtimeProvider, crypto_quote, fetch_crypto_historical_bars
from ...symbol_catalog import COINBASE_PROVIDER
from ..profiles import CRYPTO_24_7


class CoinbaseMarketDataProvider:
    provider_id = COINBASE_PROVIDER
    provider_label_zh = "Coinbase"
    profile = CRYPTO_24_7

    def __init__(self, client=None, realtime=None):
        self.client = client or CoinbasePublicClient()
        self.realtime = realtime or CoinbaseRealtimeProvider(client=self.client)

    def capabilities(self, market_id=None):
        return {"catalog": True, "quote": True, "history": True, "streaming": True, "public": True, "market": self.profile.market_id}

    def status(self, market_id=None, symbol=None):
        return {"status": "ready", "provider": self.provider_id, "mode": "realtime", "public": True}

    def list_securities(self, market_id="CRYPTO", query="", page=1):
        return [item.__dict__ for item in CoinbaseCryptoCatalogAdapter(client=self.client).fetch_market("crypto").symbols]

    def quote(self, symbol):
        return crypto_quote(str(symbol).upper().removeprefix("CC."), client=self.client)

    def fetch_window(self, symbol, timeframe, **kwargs):
        product = str(symbol).upper().removeprefix("CC.")
        rows = fetch_crypto_historical_bars(product, timeframe, count=int(kwargs.get("limit", 300)), client=self.client, before=kwargs.get("before"))
        completed = []
        for row in rows:
            completed.append({**row, "provider": self.provider_id, "market": self.profile.market_id, "symbol": str(symbol).upper(), "period": timeframe, "is_closed": True, "timestamp": row.get("time"), "sequence": None, "revision": 0, "mode": "historical"})
        return {"completed": completed, "forming": None, "meta": {"mode": "historical", "source": self.provider_id, "data_status": "historical"}}

    def fetch_recent(self, symbol, timeframe, **kwargs):
        return self.fetch_window(symbol, timeframe, **kwargs)

    def subscribe(self, symbol, timeframe, callback):
        return self.realtime.subscribe(symbol, timeframe, callback)

    def unsubscribe(self, symbol, timeframe):
        return self.realtime.unsubscribe(symbol, timeframe)
