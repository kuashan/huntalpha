from abc import ABC, abstractmethod


REALTIME_PERIOD_SUBTYPES = {
    "1分": "K_1M",
    "5分": "K_5M",
    "15分": "K_15M",
    "30分": "K_30M",
    "60分": "K_60M",
    "2小时": "K_120M",
    "4小时": "K_240M",
    "日线": "K_DAY",
    "周线": "K_WEEK",
    "月线": "K_MON",
}


class RealtimeProviderError(RuntimeError):
    """A real provider is unavailable or rejected a subscription."""


class RealtimeMarketProvider(ABC):
    provider_name = "unknown"

    @abstractmethod
    def subscribe(self, symbol, period, callback):
        raise NotImplementedError

    @abstractmethod
    def unsubscribe(self, symbol, period):
        raise NotImplementedError

    @abstractmethod
    def latest_snapshot(self, symbol, period):
        raise NotImplementedError

    @abstractmethod
    def close(self):
        raise NotImplementedError
