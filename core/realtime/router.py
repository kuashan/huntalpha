"""Provider routing while retaining one shared realtime registry."""

from .contracts import market_for_symbol
from .provider import RealtimeMarketProvider, RealtimeProviderError


class MarketDataProviderRouter(RealtimeMarketProvider):
    provider_name = "market-router"

    def __init__(self, *providers):
        if not providers:
            raise ValueError("至少需要一个实时行情 Provider")
        self.providers = tuple(providers)
        # Compatibility aliases are kept for older injected tests only. The
        # default composition no longer passes a Futu provider here.
        self.futu_provider = next((item for item in self.providers if item.provider_name == "futu-opend"), None)
        self.crypto_provider = next((item for item in self.providers if item.provider_name == "coinbase"), None)

    @property
    def provider_names(self):
        return tuple(provider.provider_name for provider in self.providers)

    def provider_for(self, symbol):
        market = market_for_symbol(symbol)
        for provider in self.providers:
            supported = getattr(provider, "supported_markets", None)
            if supported is not None and market in supported:
                return provider
            if supported is None:
                if market == "crypto" and provider.provider_name == "coinbase":
                    return provider
                if market != "crypto" and provider.provider_name != "coinbase":
                    return provider
        raise RealtimeProviderError(f"没有配置 {market or 'unknown'} 市场的实时行情 Provider", status="not_configured")

    def provider_name_for(self, symbol):
        return self.provider_for(symbol).provider_name

    def subscribe(self, symbol, period, callback):
        return self.provider_for(symbol).subscribe(symbol, period, callback)

    def unsubscribe(self, symbol, period):
        return self.provider_for(symbol).unsubscribe(symbol, period)

    def latest_snapshot(self, symbol, period):
        return self.provider_for(symbol).latest_snapshot(symbol, period)

    def health_check(self):
        statuses = []
        for provider in self.providers:
            if provider is None:
                continue
            callbacks = getattr(provider, "_callbacks", None)
            products = getattr(provider, "_products", None)
            if callbacks is not None and not callbacks:
                continue
            if products is not None and not products:
                continue
            check = getattr(provider, "health_check", None)
            if check is not None:
                statuses.append(check())
        if "unavailable" in statuses:
            return "unavailable"
        if "not_configured" in statuses:
            return "not_configured"
        if "reconnecting" in statuses:
            return "reconnecting"
        return "live" if statuses else "unavailable"

    def close(self):
        errors = []
        for provider in self.providers:
            if provider is None:
                continue
            try:
                provider.close()
            except Exception as exc:
                errors.append(exc)
        if errors:
            raise RealtimeProviderError(str(errors[0]))
