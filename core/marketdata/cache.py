from __future__ import annotations

import re
from pathlib import Path
from threading import RLock
from copy import deepcopy


_SAFE_PART = re.compile(r"[^A-Z0-9_.-]+")


def _safe_part(value: str) -> str:
    return _SAFE_PART.sub("_", str(value or "").strip().upper()) or "EMPTY"


def cache_key(market_id: str, symbol: str, timeframe: str, provider_id: str) -> tuple[str, str, str, str]:
    """Return the immutable four-dimensional cache identity."""
    return (
        str(market_id or "").strip().upper(),
        str(symbol or "").strip().upper(),
        str(timeframe or "").strip().lower(),
        str(provider_id or "").strip().upper(),
    )


def cache_path(root: str | Path, market_id: str, symbol: str, timeframe: str, provider_id: str) -> Path:
    market, code, period, provider = cache_key(market_id, symbol, timeframe, provider_id)
    return Path(root) / f"{provider}__{market}__{code}__{period}.json"


class MarketDataCache:
    """Small process-local cache with a provider-scoped identity.

    The cache is deliberately not a cross-provider merge layer.  It stores a
    complete `MarketDataFetch` per four-dimensional key and only returns a
    stale value for that exact key after all live providers fail.
    """

    def __init__(self):
        self._entries = {}
        self._lock = RLock()

    def put(self, fetch):
        key = cache_key(fetch.market_id, fetch.symbol, fetch.timeframe, fetch.provider_id)
        with self._lock:
            self._entries[key] = deepcopy(fetch)

    def get(self, market_id, symbol, timeframe, provider_id):
        key = cache_key(market_id, symbol, timeframe, provider_id)
        with self._lock:
            value = self._entries.get(key)
            return deepcopy(value) if value is not None else None

    def keys(self):
        with self._lock:
            return tuple(self._entries)
