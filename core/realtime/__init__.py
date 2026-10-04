"""Process-local real-time market data services for the development runtime."""

from .contracts import (
    MARKET_TIMEZONES,
    MergeResult,
    NormalizedBar,
    market_for_symbol,
    merge_realtime_bar,
    optional_numeric,
    provider_time_to_timestamp,
    timestamp_to_market_datetime,
)
from .longbridge_provider import LongbridgeRealtimeProvider
from .router import MarketDataProviderRouter
from .provider import RealtimeProviderError
from .registry import RealtimeConsumer, RealtimeRegistry, get_realtime_registry
from .state import RealtimeStateStore
from .tushare_provider import TushareRealtimeProvider

__all__ = [
    "FutuRealtimeProvider",
    "LongbridgeRealtimeProvider",
    "TushareRealtimeProvider",
    "MarketDataProviderRouter",
    "MARKET_TIMEZONES",
    "MergeResult",
    "NormalizedBar",
    "RealtimeConsumer",
    "RealtimeRegistry",
    "RealtimeStateStore",
    "get_realtime_registry",
    "market_for_symbol",
    "merge_realtime_bar",
    "optional_numeric",
    "provider_time_to_timestamp",
    "timestamp_to_market_datetime",
    "RealtimeProviderError",
]


def __getattr__(name):
    """Load the legacy Futu adapter only when an explicit caller asks for it."""
    if name == "FutuRealtimeProvider":
        from .futu_provider import FutuRealtimeProvider

        return FutuRealtimeProvider
    raise AttributeError(name)
