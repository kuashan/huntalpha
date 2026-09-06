"""Provider routing while retaining one shared realtime registry."""

from .provider import RealtimeMarketProvider, RealtimeProviderError


class MarketDataProviderRouter(RealtimeMarketProvider):
    provider_name = "market-router"

    def __init__(self, futu_provider, crypto_provider):
        self.futu_provider = futu_provider
        self.crypto_provider = crypto_provider

    @staticmethod
    def is_crypto(symbol):
        return str(symbol or "").upper().startswith("CC.")

    def provider_for(self, symbol):
        return self.crypto_provider if self.is_crypto(symbol) else self.futu_provider

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
        for provider in (self.futu_provider, self.crypto_provider):
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
        if "reconnecting" in statuses:
            return "reconnecting"
        return "live" if statuses else "unavailable"

    def close(self):
        errors = []
        for provider in (self.futu_provider, self.crypto_provider):
            try:
                provider.close()
            except Exception as exc:
                errors.append(exc)
        if errors:
            raise RealtimeProviderError(str(errors[0]))
