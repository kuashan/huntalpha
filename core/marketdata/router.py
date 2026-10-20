from __future__ import annotations

from dataclasses import replace
from typing import Any

from .cache import MarketDataCache
from .contracts import MarketDataFetch, MarketDataProvider
from .profiles import normalize_market_id
from .providers.base import MarketDataProviderError


class MarketDataRouter:
    """Route by MarketProfile and Provider priority with whole-window failover."""

    def __init__(self, cache: MarketDataCache | None = None, selection_resolver=None):
        self._providers: dict[str, list[MarketDataProvider]] = {}
        self.cache = cache or MarketDataCache()
        self.selection_resolver = selection_resolver

    def register(self, provider: MarketDataProvider) -> None:
        market_id = normalize_market_id(provider.profile.market_id)
        self._providers.setdefault(market_id, []).append(provider)

    def provider_ids(self, market_id: str) -> tuple[str, ...]:
        return tuple(provider.provider_id for provider in self.all_providers_for(market_id))

    def all_providers_for(self, market_id: str):
        """Registered sources irrespective of the operator's quote/K-line choice."""
        return tuple(self._providers.get(normalize_market_id(market_id), ()))

    def providers_for(self, market_id: str):
        """Auto: existing priority/failover. Manual: the selected source only."""
        market = normalize_market_id(market_id)
        registered = self.all_providers_for(market)
        selected = self.selection_resolver(market) if self.selection_resolver else "auto"
        if selected in ("auto", None):
            return registered
        chosen = tuple(provider for provider in registered if provider.provider_id == selected)
        if not chosen:
            raise MarketDataProviderError(f"{market}: 手动指定的行情源不可用：{selected}", status="not_configured")
        return chosen

    def provider_for(self, market_id: str, provider_id: str | None = None):
        return self._provider(market_id, provider_id)

    def fetch_window(self, market_id: str, symbol: str, timeframe: str, **kwargs: Any) -> MarketDataFetch:
        market = normalize_market_id(market_id)
        providers = self.providers_for(market)
        if not providers:
            raise RuntimeError(f"没有可用行情供应商：{market}")

        errors: list[str] = []
        stale = []
        for provider in providers:
            try:
                fetcher = getattr(provider, "fetch_window", None)
                if not callable(fetcher):
                    fetcher = getattr(provider, "fetch", None)
                if not callable(fetcher):
                    raise TypeError("provider has no complete-window fetcher")
                payload = fetcher(symbol, timeframe, **kwargs)
                stream_factory = getattr(provider, "stream_url", None)
                stream_url = stream_factory(symbol) if callable(stream_factory) else None
                fetch = MarketDataFetch.from_payload(
                    market_id=market,
                    provider_id=provider.provider_id,
                    provider_label_zh=provider.provider_label_zh,
                    symbol=symbol,
                    timeframe=timeframe,
                    payload=payload,
                    stream_url=stream_url,
                )
                self.cache.put(fetch)
                return fetch
            except Exception as exc:
                errors.append(f"{provider.provider_id}:{getattr(exc, 'status', 'unavailable')}:{type(exc).__name__}:{exc}")
                cached = self.cache.get(market, symbol, timeframe, provider.provider_id)
                if cached is not None:
                    stale.append(cached)
        if stale:
            cached = stale[0]
            return replace(
                cached,
                meta={
                    **cached.meta,
                    "mode": "cache",
                    "stale": True,
                    "error": "；".join(errors),
                },
            )
        status = "not_configured" if errors and all(":not_configured:" in item for item in errors) else "unavailable"
        raise MarketDataProviderError("；".join(errors) or f"{market}: 行情获取失败", status=status)

    def quote(self, market_id: str, symbol: str) -> dict[str, Any]:
        """Return one complete quote from the first healthy provider.

        Quote failover follows the same provider boundary as historical
        windows: a provider either supplies the whole quote or the next
        provider is tried.  No fields are merged across providers.
        """
        market = normalize_market_id(market_id)
        providers = self.providers_for(market)
        if not providers:
            raise MarketDataProviderError(f"没有可用行情供应商：{market}", status="not_configured")
        errors: list[str] = []
        for provider in providers:
            try:
                quote = getattr(provider, "quote", None)
                if not callable(quote):
                    raise MarketDataProviderError("provider does not support quote")
                payload = quote(symbol)
                if not isinstance(payload, dict) or payload.get("price") is None:
                    raise MarketDataProviderError("provider returned an incomplete quote")
                return dict(payload)
            except Exception as exc:
                errors.append(f"{provider.provider_id}:{getattr(exc, 'status', 'unavailable')}:{type(exc).__name__}:{exc}")
        status = "not_configured" if errors and all(":not_configured:" in item for item in errors) else "unavailable"
        raise MarketDataProviderError("；".join(errors) or f"{market}: 报价获取失败", status=status)

    def capabilities(self, market_id: str, provider_id: str | None = None) -> dict[str, Any]:
        provider = self._provider(market_id, provider_id)
        method = getattr(provider, "capabilities", None)
        return dict(method(market_id) if callable(method) else {})

    def status(self, market_id: str, provider_id: str | None = None, symbol: str | None = None) -> dict[str, Any]:
        provider = self._provider(market_id, provider_id)
        method = getattr(provider, "status", None)
        return dict(method(market_id, symbol) if callable(method) else {"status": "unknown", "provider": provider.provider_id})

    def _provider(self, market_id: str, provider_id: str | None):
        providers = self.providers_for(market_id)
        if provider_id is None:
            if not providers:
                raise RuntimeError(f"没有可用行情供应商：{normalize_market_id(market_id)}")
            return providers[0]
        for provider in providers:
            if provider.provider_id == provider_id:
                return provider
        raise KeyError(f"provider is not registered for market: {provider_id}")
