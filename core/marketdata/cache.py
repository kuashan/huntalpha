from __future__ import annotations

import re
from pathlib import Path


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
