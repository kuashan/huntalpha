"""Provider-neutral definitions and adapters for the terminal index header.

The provider symbols in this module are identity mappings, not market data.
They were verified against the local Futu SDK/OpenD catalog before being
added.  Runtime values always come from the OpenD snapshot response.
"""

from dataclasses import dataclass
import math

from futu import RET_OK


INDEX_SOURCE = "futu-opend"


@dataclass(frozen=True)
class MarketIndexDefinition:
    key: str
    market: str
    name: str
    provider_code: str
    provider_name: str


# These are the seven index identities confirmed by the local OpenD catalog.
# Do not add price or change values here: all such values are runtime data.
INDEX_DEFINITIONS = (
    MarketIndexDefinition("shanghai", "cn", "上证指数", "SH.000001", "上证指数"),
    MarketIndexDefinition("shenzhen", "cn", "深证成指", "SZ.399001", "深证成指"),
    MarketIndexDefinition("hsi", "hk", "恒生指数", "HK.800000", "恒生指数"),
    MarketIndexDefinition("hstech", "hk", "恒生科技指数", "HK.800700", "恒生科技指数"),
    MarketIndexDefinition("sp500", "us", "标普500", "US..SPX", "标普500指数"),
    MarketIndexDefinition("nasdaq_composite", "us", "纳斯达克综合指数", "US..IXIC", "纳斯达克综合指数"),
    MarketIndexDefinition("dow_jones", "us", "道琼斯工业平均指数", "US..DJI", "道琼斯指数"),
)

INDEX_DEFINITIONS_BY_MARKET = {
    market: tuple(item for item in INDEX_DEFINITIONS if item.market == market)
    for market in ("cn", "hk", "us")
}


def finite_number(value):
    """Return a finite float, or None for provider null/NaN/N/A values."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _text_value(value):
    if value is None:
        return None
    text = str(value).strip()
    return text if text and text.upper() not in {"N/A", "NAN", "NONE"} else None


def _row_value(row, key):
    if hasattr(row, "get"):
        return row.get(key)
    if hasattr(row, key):
        return getattr(row, key)
    try:
        return row[key]
    except (KeyError, IndexError, TypeError):
        return None


def _snapshot_item(definition, row=None, error=None):
    provider_name = _text_value(_row_value(row, "name")) if row is not None else None
    price = finite_number(_row_value(row, "last_price")) if row is not None else None
    previous_close = finite_number(_row_value(row, "prev_close_price")) if row is not None else None
    change = None
    change_percent = None
    if price is not None and previous_close is not None and previous_close > 0:
        change = price - previous_close
        change_percent = change / previous_close * 100

    if price is None:
        status = "unavailable"
        safe_error = error or "当前指数真实报价不可用"
    elif previous_close is None or previous_close <= 0:
        status = "partial"
        safe_error = error or "当前指数昨收不可用"
    else:
        status = "ok"
        safe_error = None

    item = {
        "code": definition.provider_code,
        "name": definition.name,
        "provider_name": provider_name or definition.provider_name,
        "market": definition.market,
        "price": price,
        "previous_close": previous_close,
        "change": change,
        "change_percent": change_percent,
        "open": finite_number(_row_value(row, "open_price")) if row is not None else None,
        "high": finite_number(_row_value(row, "high_price")) if row is not None else None,
        "low": finite_number(_row_value(row, "low_price")) if row is not None else None,
        "updated_at": _text_value(_row_value(row, "update_time")) if row is not None else None,
        "status": status,
        "source": INDEX_SOURCE,
    }
    if safe_error:
        item["error"] = safe_error
    return item


def convert_snapshot_frame(frame, definitions=INDEX_DEFINITIONS, error=None):
    """Convert an OpenD DataFrame-like result without exposing provider errors."""
    rows = {}
    if frame is not None and hasattr(frame, "iterrows"):
        for _, row in frame.iterrows():
            code = _text_value(_row_value(row, "code"))
            if code:
                rows[code.upper()] = row
    elif frame is not None and hasattr(frame, "itertuples"):
        for row in frame.itertuples(index=False):
            code = _text_value(_row_value(row, "code"))
            if code:
                rows[code.upper()] = row

    return [
        _snapshot_item(
            definition,
            rows.get(definition.provider_code.upper()),
            error=error or ("OpenD 未返回该指数快照" if definition.provider_code.upper() not in rows else None),
        )
        for definition in definitions
    ]


class FutuOpenDIndexAdapter:
    """Fetch three market-isolated batches from the current OpenD instance."""

    def __init__(self, context_factory):
        self.context_factory = context_factory
        self.open_d_calls = 0

    def _fetch_market(self, client, definitions):
        codes = [definition.provider_code for definition in definitions]
        self.open_d_calls += 1
        try:
            ret, frame = client.get_market_snapshot(codes)
        except Exception:
            ret, frame = -1, None
        if ret == RET_OK:
            return convert_snapshot_frame(frame, definitions)

        # The current OpenD explicitly reports that US indices are not
        # supported. There is no point in repeating the same unsupported call
        # for every US symbol, and an ETF must never be used as a proxy.
        if "暂不支持美股指数" in str(frame):
            return [_snapshot_item(definition, error="当前 OpenD 不支持该美股指数") for definition in definitions]

        # A single malformed/unsupported symbol can make a provider batch
        # fail. Retry that small market one symbol at a time so an isolated
        # failure never hides valid rows from the same market.
        result = []
        for definition in definitions:
            self.open_d_calls += 1
            try:
                single_ret, single_frame = client.get_market_snapshot([definition.provider_code])
            except Exception:
                single_ret, single_frame = -1, None
            if single_ret == RET_OK:
                result.extend(convert_snapshot_frame(single_frame, (definition,)))
            else:
                result.append(_snapshot_item(definition, error="当前指数真实报价不可用"))
        return result

    def fetch(self):
        try:
            client = self.context_factory()
        except Exception:
            return [_snapshot_item(definition, error="富途 OpenD 当前不可用") for definition in INDEX_DEFINITIONS]

        try:
            items = []
            for definitions in INDEX_DEFINITIONS_BY_MARKET.values():
                items.extend(self._fetch_market(client, definitions))
            return items
        finally:
            client.close()


def unavailable_index_items(error="富途 OpenD 当前不可用"):
    return [_snapshot_item(definition, error=error) for definition in INDEX_DEFINITIONS]


def grouped_snapshot_response(items):
    return {
        "source": INDEX_SOURCE,
        "markets": [
            {
                "market": market,
                "items": [item for item in items if item["market"] == market],
            }
            for market in ("cn", "hk", "us")
        ],
    }
