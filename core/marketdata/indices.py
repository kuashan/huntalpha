from __future__ import annotations

import math
from collections.abc import Mapping, Sequence

from ..market_indices import INDEX_DEFINITIONS, MarketIndexDefinition


# Index identities are provider-specific request symbols, never quote values.
# Keep this mapping at the provider boundary so callers retain the established
# HuntAlpha index identity while no Futu SDK is opened at runtime.
INDEX_SYMBOLS_BY_PROVIDER = {
    "yahoo-finance": {
        "shanghai": "SH.000001",
        "shenzhen": "SZ.399001",
        "hsi": "US.^HSI",
        "hstech": "US.^HSTECH",
        "sp500": "US.^GSPC",
        "nasdaq_composite": "US.^IXIC",
        "dow_jones": "US.^DJI",
    },
    "tencent-public": {
        "shanghai": "SH.000001",
        "shenzhen": "SZ.399001",
        "hsi": "INDEX.HSI",
        "hstech": "INDEX.HSTECH",
    },
}


def _finite_number(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


class UnifiedIndexSnapshotAdapter:
    """Fetch independent index snapshots through registered market providers.

    This adapter deliberately does not call Futu/OpenD.  Each index is
    resolved against a provider-specific identity, so a provider failure only
    affects that index and never produces a proxy, static value, or cross-
    provider field merge.
    """

    def __init__(self, providers_by_market: Mapping[str, Sequence[object]]):
        self.providers_by_market = {
            str(market).lower(): tuple(providers)
            for market, providers in providers_by_market.items()
        }
        self.definitions_by_key = {definition.key: definition for definition in INDEX_DEFINITIONS}

    def snapshot_item(self, key: str) -> dict:
        definition = self.definitions_by_key[key]
        for provider in self.providers_by_market.get(definition.market, ()):
            provider_id = getattr(provider, "provider_id", "")
            provider_symbol = INDEX_SYMBOLS_BY_PROVIDER.get(provider_id, {}).get(definition.key)
            if not provider_symbol:
                continue
            try:
                quote = provider.quote(provider_symbol)
            except Exception:
                continue
            item = self._item_from_quote(definition, quote, provider_id)
            if item["price"] is not None:
                return item
        return self._unavailable_item(definition)

    def snapshot_response(self) -> dict:
        items = [self.snapshot_item(definition.key) for definition in INDEX_DEFINITIONS]
        return {
            "source": "marketdata-router",
            "markets": [
                {"market": market, "items": [item for item in items if item["market"] == market]}
                for market in ("cn", "hk", "us")
            ],
        }

    @staticmethod
    def _item_from_quote(definition: MarketIndexDefinition, quote, provider_id: str) -> dict:
        payload = quote if isinstance(quote, dict) else {}
        price = _finite_number(payload.get("price"))
        previous_close = _finite_number(payload.get("previous_close"))
        change = None
        change_percent = None
        if price is not None and previous_close is not None and previous_close > 0:
            change = price - previous_close
            change_percent = change / previous_close * 100
        status = "ok" if change_percent is not None else ("partial" if price is not None else "unavailable")
        item = {
            "code": definition.provider_code,
            "name": definition.name,
            "provider_name": definition.provider_name,
            "market": definition.market,
            "price": price,
            "previous_close": previous_close,
            "change": change,
            "change_percent": change_percent,
            "open": _finite_number(payload.get("open")),
            "high": _finite_number(payload.get("high")),
            "low": _finite_number(payload.get("low")),
            "updated_at": payload.get("updated_at"),
            "status": status,
            "source": payload.get("source") or provider_id,
            "data_status": payload.get("data_status"),
        }
        if status != "ok":
            item["error"] = "当前指数真实报价不完整"
        return item

    @staticmethod
    def _unavailable_item(definition: MarketIndexDefinition) -> dict:
        return {
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
            "status": "unavailable",
            "source": "marketdata-router",
            "error": "当前指数真实报价不可用",
        }
