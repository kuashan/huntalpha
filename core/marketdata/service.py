from __future__ import annotations

from typing import Any

from .contracts import MarketDataFetch
from .profiles import CN_A_SHARE, CRYPTO_24_7, HK_EQUITY, US_EQUITY
from .providers.coinbase import CoinbaseMarketDataProvider
from .providers.longbridge import LongbridgeMarketDataProvider
from .providers.tushare import TushareMarketDataProvider
from .router import MarketDataRouter


def legacy_coinbase_client():
    """Construct the old Coinbase client only for explicit test compatibility."""
    from ..crypto_provider import CoinbasePublicClient

    return CoinbasePublicClient()


def legacy_crypto_quote(*args, **kwargs):
    from ..crypto_provider import crypto_quote

    return crypto_quote(*args, **kwargs)


def legacy_fetch_crypto_historical_bars(*args, **kwargs):
    from ..crypto_provider import fetch_crypto_historical_bars

    return fetch_crypto_historical_bars(*args, **kwargs)


def build_realtime_provider():
    """Compose the provider-neutral realtime router.

    A-shares use Tushare's explicit polling seam, HK/US use Longbridge's
    candlestick push seam, and crypto keeps the public Coinbase stream. Futu
    remains importable only as an explicit legacy adapter and is never part of
    the default runtime composition.
    """
    from ..crypto_provider import CoinbaseRealtimeProvider
    from ..realtime.longbridge_provider import LongbridgeRealtimeProvider
    from ..realtime.router import MarketDataProviderRouter
    from ..realtime.tushare_provider import TushareRealtimeProvider

    return MarketDataProviderRouter(
        LongbridgeRealtimeProvider(),
        TushareRealtimeProvider(),
        CoinbaseRealtimeProvider(),
    )


def market_id_for_symbol(symbol: str) -> str:
    prefix = str(symbol or "").strip().upper().split(".", 1)[0]
    return {"SH": CN_A_SHARE.market_id, "SZ": CN_A_SHARE.market_id, "HK": HK_EQUITY.market_id, "US": US_EQUITY.market_id, "CC": CRYPTO_24_7.market_id}.get(prefix, US_EQUITY.market_id)


def build_market_data_router() -> MarketDataRouter:
    router = MarketDataRouter()
    router.register(TushareMarketDataProvider())
    router.register(LongbridgeMarketDataProvider(market=CN_A_SHARE))
    router.register(LongbridgeMarketDataProvider(market=HK_EQUITY))
    router.register(LongbridgeMarketDataProvider(market=US_EQUITY))
    router.register(CoinbaseMarketDataProvider())
    return router


class MarketDataService:
    def __init__(self, router: MarketDataRouter | None = None):
        self.router = router or build_market_data_router()

    def provider_for_symbol(self, symbol: str):
        return self.router.provider_for(market_id_for_symbol(symbol))

    def quote_for_symbol(self, symbol: str) -> dict:
        provider = self.provider_for_symbol(symbol)
        quote = getattr(provider, "quote", None)
        if not callable(quote):
            raise RuntimeError(f"{provider.provider_id} 不支持报价")
        return dict(quote(symbol))

    def window_for_symbol(self, symbol: str, timeframe: str, **kwargs: Any) -> MarketDataFetch:
        return self.router.fetch_window(market_id_for_symbol(symbol), symbol, timeframe, **kwargs)

    def status_for_symbol(self, symbol: str) -> dict:
        provider = self.provider_for_symbol(symbol)
        return self.router.status(market_id_for_symbol(symbol), provider.provider_id, symbol)

    def catalog_snapshot(self, market: str):
        """Fetch one complete provider-scoped security catalog.

        Catalog failover follows the same whole-request rule as K-lines: a
        provider either supplies the complete snapshot or the next provider
        is tried.  No symbols are merged across providers.
        """
        from ..symbol_catalog import (
            MARKET_DEFINITIONS,
            ProviderCatalogSnapshot,
            ProviderSymbol,
            ProviderSyncError,
        )

        normalized = str(market or "").strip().lower()
        if normalized not in MARKET_DEFINITIONS:
            raise ProviderSyncError("unsupported_market")
        profile_id = {"cn": CN_A_SHARE.market_id, "hk": HK_EQUITY.market_id, "us": US_EQUITY.market_id}[normalized]
        errors = []
        for provider in self.router.providers_for(profile_id):
            try:
                rows = provider.list_securities(profile_id, query="", page=1)
                symbols = tuple(self._catalog_symbol(row, normalized, provider.provider_id) for row in (rows or []))
                symbols = tuple(item for item in symbols if item is not None)
                if not symbols:
                    raise ProviderSyncError("suspicious_empty_catalog")
                return ProviderCatalogSnapshot(
                    normalized, symbols, {}, market_cap_error="not_available", provider=provider.provider_id,
                )
            except Exception as exc:
                errors.append(f"{provider.provider_id}:{type(exc).__name__}")
        raise ProviderSyncError("catalog_unavailable:" + ",".join(errors))

    @staticmethod
    def _catalog_symbol(row, market: str, provider_id: str):
        from ..symbol_catalog import ProviderSymbol

        def value(*names, default=None):
            if isinstance(row, dict):
                for name in names:
                    if row.get(name) is not None:
                        return row.get(name)
            for name in names:
                if hasattr(row, name):
                    return getattr(row, name)
            return default

        raw = str(value("code", "ts_code", "symbol", "ticker", default="") or "").strip().upper()
        if not raw:
            return None
        if "." in raw:
            left, suffix = raw.rsplit(".", 1)
            prefix = {"SH": "SH.", "SZ": "SZ.", "SSE": "SH.", "SZSE": "SZ.", "HK": "HK."}.get(suffix)
            code = f"{prefix}{left}" if prefix else f"US.{left}"
        elif market == "hk":
            code = f"HK.{raw}"
        elif market == "us":
            code = f"US.{raw}"
        else:
            code = raw
        exchange = str(value("exchange", "exchange_type", default=market.upper()) or market.upper())
        currency = {"cn": "CNY", "hk": "HKD", "us": "USD"}[market]
        return ProviderSymbol(
            code=code,
            name=str(value("name", "stock_name", "company_name", default=code) or code),
            market=market,
            exchange=exchange,
            security_type="STOCK",
            active=True,
            provider=provider_id,
            market_cap_currency=currency,
            market_cap_eligible=True,
            provider_symbol=raw,
        )

    def legacy_window(self, symbol: str, timeframe: str, context_factory=None, **kwargs: Any) -> MarketDataFetch:
        from .providers.futu_legacy import FutuLegacyMarketDataProvider

        market = market_id_for_symbol(symbol)
        profile = {CN_A_SHARE.market_id: CN_A_SHARE, HK_EQUITY.market_id: HK_EQUITY, US_EQUITY.market_id: US_EQUITY}.get(market)
        if profile is None:
            raise RuntimeError("Futu legacy 不支持加密资产")
        provider = FutuLegacyMarketDataProvider(profile, context_factory=context_factory)
        return MarketDataFetch.from_payload(market_id=market, provider_id=provider.provider_id, provider_label_zh=provider.provider_label_zh, symbol=symbol, timeframe=timeframe, payload=provider.fetch_window(symbol, timeframe, **kwargs))

    def legacy_context(self):
        """Open the explicitly requested OpenD compatibility context.

        This method is intentionally outside the default router.  It exists
        only for the old API/test seam while all normal application requests
        go through the provider-neutral service methods.
        """
        from .providers.futu_legacy import FutuLegacyMarketDataProvider

        provider = FutuLegacyMarketDataProvider(CN_A_SHARE)
        return provider.open_context()

    def index_snapshot_response(self) -> dict:
        """Return provider-neutral index availability without opening OpenD.

        Index-specific providers are not configured yet, so this endpoint
        reports explicit unavailable/not_configured states instead of routing
        through the legacy Futu adapter or inventing index values.
        """
        from ..market_indices import INDEX_DEFINITIONS

        items = []
        profile_ids = {"cn": CN_A_SHARE.market_id, "hk": HK_EQUITY.market_id, "us": US_EQUITY.market_id}
        for definition in INDEX_DEFINITIONS:
            provider_ids = self.router.provider_ids(profile_ids.get(definition.market, definition.market))
            status = "not_configured" if provider_ids else "unavailable"
            items.append({
                "code": definition.provider_code,
                "name": definition.name,
                "provider_name": definition.provider_name,
                "market": definition.market,
                "price": None,
                "previous_close": None,
                "change": None,
                "change_percent": None,
                "open": None,
                "high": None,
                "low": None,
                "updated_at": None,
                "status": status,
                "source": provider_ids[0] if provider_ids else "marketdata-router",
                "error": "统一行情源未配置" if status == "not_configured" else "统一行情源不可用",
            })
        return {
            "source": "marketdata-router",
            "markets": [
                {"market": market, "items": [item for item in items if item["market"] == market]}
                for market in ("cn", "hk", "us")
            ],
        }

    def legacy_quote(self, symbol: str, context_factory=None) -> dict:
        from .providers.futu_legacy import FutuLegacyMarketDataProvider

        market = market_id_for_symbol(symbol)
        profile = {CN_A_SHARE.market_id: CN_A_SHARE, HK_EQUITY.market_id: HK_EQUITY, US_EQUITY.market_id: US_EQUITY}.get(market)
        if profile is None:
            raise RuntimeError("Futu legacy 不支持加密资产")
        return FutuLegacyMarketDataProvider(profile, context_factory=context_factory).quote(symbol)


_SERVICE = None


def get_market_data_service() -> MarketDataService:
    global _SERVICE
    if _SERVICE is None:
        _SERVICE = MarketDataService()
    return _SERVICE
