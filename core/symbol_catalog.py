from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import math
import os

from django.db import transaction
from django.utils import timezone
from futu import Market, OpenQuoteContext, RET_OK, SimpleFilter, SortDir, StockField

from .models import MarketSymbol


FUTU_PROVIDER = "futu-opend"
COINBASE_PROVIDER = "coinbase"
MAX_MARKET_CAP_ROWS = 200


@dataclass(frozen=True)
class MarketDefinition:
    code: str
    name: str
    provider_markets: tuple
    market_cap_markets: tuple
    currency: str


MARKET_DEFINITIONS = {
    "cn": MarketDefinition("cn", "沪深 A 股", (Market.SH, Market.SZ), (Market.SH, Market.SZ), "CNY"),
    "hk": MarketDefinition("hk", "港股", (Market.HK,), (Market.HK,), "HKD"),
    "us": MarketDefinition("us", "美股", (Market.US,), (Market.US,), "USD"),
}
CRYPTO_MARKET = "crypto"
SUPPORTED_MARKETS = tuple(MARKET_DEFINITIONS) + (CRYPTO_MARKET,)


@dataclass(frozen=True)
class ProviderSymbol:
    code: str
    name: str
    market: str
    exchange: str
    security_type: str
    active: bool
    provider: str = FUTU_PROVIDER
    market_cap_currency: str | None = None
    market_cap_eligible: bool = True
    provider_symbol: str | None = None


@dataclass(frozen=True)
class ProviderCatalogSnapshot:
    market: str
    symbols: tuple
    market_caps: dict
    market_cap_error: str | None = None
    market_cap_reset_codes: tuple = ()
    provider: str = FUTU_PROVIDER


class ProviderSyncError(RuntimeError):
    def __init__(self, error_type):
        self.error_type = error_type
        super().__init__(error_type)


def _field(row, name, default=""):
    return getattr(row, name, default)


def _text(value):
    if value is None:
        return ""
    text = str(value).strip()
    return "" if text in {"", "N/A", "nan", "None"} else text


def _truthy(value):
    return value is True or str(value).strip().lower() in {"1", "true", "yes"}


def _positive_number(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) and number > 0 else None


def _decimal_market_cap(value):
    number = _positive_number(value)
    if number is None:
        return None
    try:
        return Decimal(str(number)).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError):
        return None


def _provider_market_prefix(provider_market):
    return {
        Market.SH: "SH.",
        Market.SZ: "SZ.",
    }.get(provider_market)


def _provider_currency(row):
    """Return an explicitly supplied provider currency, when one exists."""
    for field_name in (
        "currency", "market_currency", "quote_currency", "trading_currency",
        "stock_currency", "market_cap_currency",
    ):
        value = _text(_field(row, field_name))
        if value:
            value = value.upper()
            return {"RMB": "CNY", "CNH": "CNY"}.get(value, value)
    return None


def _is_hk_alternate_counter(row, code):
    """Identify HK alternate-currency counters from provider attributes.

    OpenD currently does not expose a currency column for HK stock basic info or
    snapshots.  Prefer an explicit currency/counter attribute when available;
    otherwise use the provider's alternate-counter name/code
    convention.  This is deliberately generic and never names an individual
    security.
    """
    for field_name in (
        "currency", "market_currency", "quote_currency", "trading_currency",
        "stock_currency", "market_cap_currency", "counter_currency",
        "counter_type", "stock_child_type",
    ):
        value = _text(_field(row, field_name)).upper()
        if value in {"RMB", "CNY", "CNH", "RMB_COUNTER", "CNY_COUNTER", "CNH_COUNTER", "ALTERNATE"}:
            return True
        if value in {"HKD", "HKD_COUNTER", "PRIMARY", "MAIN"}:
            return False

    name = _text(_field(row, "name")).upper()
    if name.endswith("-R") or name.endswith("-RMB") or "人民币柜台" in name:
        return True

    # HK RMB counters use the provider's 8xxxx code range.  The range check
    # is a provider symbol attribute, not a hand-maintained security list.
    provider_code = code.upper()
    local_code = provider_code[3:] if provider_code.startswith("HK.") else provider_code
    return local_code.isdigit() and len(local_code) == 5 and local_code.startswith("8")


def _default_context():
    host = os.environ.get("FUTU_OPEND_HOST", "127.0.0.1")
    try:
        port = int(os.environ.get("FUTU_OPEND_PORT", "11111"))
    except ValueError as exc:
        raise ProviderSyncError("invalid_provider_port") from exc
    try:
        return OpenQuoteContext(host=host, port=port, ai_type=1)
    except Exception as exc:
        raise ProviderSyncError("provider_connection") from exc


class FutuOpenDAdapter:
    """Translate the current Futu SDK into the HuntAlpha symbol contract."""

    def __init__(self, context_factory=None):
        self.context_factory = context_factory or _default_context

    def _catalog_rows(self, client, definition):
        rows = []
        seen = set()
        for provider_market in definition.provider_markets:
            ret, frame = client.get_stock_basicinfo(provider_market, stock_type="STOCK")
            if ret != RET_OK:
                raise ProviderSyncError("catalog_fetch_failed")
            for row in frame.itertuples(index=False):
                code = _text(_field(row, "code")).upper()
                name = _text(_field(row, "name"))
                security_type = _text(_field(row, "stock_type")).upper()
                if not code or not name or security_type != "STOCK" or code in seen:
                    continue
                seen.add(code)
                alternate_counter = definition.code == "hk" and _is_hk_alternate_counter(row, code)
                provider_currency = _provider_currency(row)
                rows.append(ProviderSymbol(
                    code=code,
                    name=name,
                    market=definition.code,
                    exchange=_text(_field(row, "exchange_type")) or str(provider_market),
                    security_type=security_type,
                    active=not _truthy(_field(row, "delisting", False)),
                    market_cap_currency=provider_currency or (None if alternate_counter else definition.currency),
                    market_cap_eligible=not alternate_counter,
                    provider_symbol=code,
                ))
        return tuple(rows)

    def _market_caps(self, client, definition, catalog_symbols):
        filter_item = SimpleFilter()
        filter_item.stock_field = StockField.MARKET_VAL
        filter_item.sort = SortDir.DESCEND
        filter_item.is_no_filter = True
        catalog_by_code = {item.code: item for item in catalog_symbols}
        market_caps = {}
        for provider_market in definition.market_cap_markets:
            expected_prefix = _provider_market_prefix(provider_market)
            begin = 0
            matched_codes = set()
            seen_pages = set()
            while True:
                ret, data = client.get_stock_filter(
                    provider_market,
                    filter_list=[filter_item],
                    begin=begin,
                    num=MAX_MARKET_CAP_ROWS,
                )
                if ret != RET_OK or not isinstance(data, tuple) or len(data) != 3:
                    raise ProviderSyncError("market_cap_fetch_failed")
                rows = list(data[2])
                page_codes = tuple(_text(_field(row, "stock_code")).upper() for row in rows)
                if page_codes in seen_pages:
                    break
                seen_pages.add(page_codes)
                for row in rows:
                    code = _text(_field(row, "stock_code")).upper()
                    if expected_prefix and not code.startswith(expected_prefix):
                        continue
                    item = catalog_by_code.get(code)
                    if expected_prefix and code in matched_codes:
                        continue
                    if expected_prefix and len(matched_codes) >= MAX_MARKET_CAP_ROWS:
                        break
                    if item is not None:
                        matched_codes.add(code)
                    value = _decimal_market_cap(_field(row, "market_val"))
                    if item is not None and item.market_cap_eligible and value is not None:
                        market_caps[code] = value

                # OpenD normally scopes the call to the requested market.  A
                # current version can return mixed SH/SZ pages instead, so
                # page through those pages until the requested exchange has
                # its own 200 candidates.
                if not expected_prefix or len(matched_codes) >= MAX_MARKET_CAP_ROWS or data[0] or not rows:
                    break
                next_begin = begin + len(rows)
                if next_begin <= begin:
                    break
                begin = next_begin
        return market_caps

    def fetch_market(self, market):
        try:
            definition = MARKET_DEFINITIONS[market]
        except KeyError as exc:
            raise ProviderSyncError("unsupported_market") from exc
        client = self.context_factory()
        try:
            symbols = self._catalog_rows(client, definition)
            if not symbols:
                raise ProviderSyncError("suspicious_empty_catalog")
            try:
                market_caps = self._market_caps(client, definition, symbols)
                market_cap_error = None
            except ProviderSyncError as exc:
                market_caps = {}
                market_cap_error = exc.error_type
            reset_codes = tuple(item.code for item in symbols if not item.market_cap_eligible)
            return ProviderCatalogSnapshot(market, symbols, market_caps, market_cap_error, reset_codes)
        finally:
            client.close()


SYNC_FIELDS = (
    "name", "market", "exchange", "security_type", "active", "provider",
    "provider_symbol", "market_cap", "market_cap_currency", "market_cap_updated_at",
    "catalog_updated_at",
)


def apply_catalog_snapshot(snapshot, now=None):
    now = now or timezone.now()
    symbols = list(snapshot.symbols)
    if not symbols:
        raise ProviderSyncError("suspicious_empty_catalog")
    codes = {item.code for item in symbols}
    with transaction.atomic():
        existing = {item.code: item for item in MarketSymbol.objects.filter(code__in=codes)}
        new_items = []
        changed_items = []
        added = 0
        updated = 0
        for item in symbols:
            market_cap = snapshot.market_caps.get(item.code)
            clear_market_cap = (
                bool(snapshot.market_cap_error)
                or item.code in snapshot.market_cap_reset_codes
                or market_cap is None
            )
            if item.market_cap_currency is None:
                currency = MARKET_DEFINITIONS[item.market].currency if item.market_cap_eligible else ""
            else:
                currency = item.market_cap_currency
            desired = {
                "code": item.code,
                "name": item.name,
                "market": item.market,
                "exchange": item.exchange,
                "security_type": item.security_type,
                "active": item.active,
                "provider": item.provider,
                "provider_symbol": item.provider_symbol or item.code,
                "market_cap": market_cap,
                "market_cap_currency": currency,
            }
            target = existing.get(item.code)
            if target is None:
                new_items.append(MarketSymbol(**desired, market_cap_updated_at=now if market_cap is not None else None, catalog_updated_at=now))
                added += 1
                continue
            was_changed = any(
                getattr(target, field) != value
                for field, value in desired.items()
                if field != "market_cap" or market_cap is not None or clear_market_cap
            )
            for field, value in desired.items():
                if field == "market_cap" and market_cap is None and not clear_market_cap:
                    continue
                setattr(target, field, value)
            if market_cap is not None:
                target.market_cap_updated_at = now
            elif clear_market_cap:
                target.market_cap_updated_at = None
            target.catalog_updated_at = now
            changed_items.append(target)
            updated += int(was_changed)
        if new_items:
            MarketSymbol.objects.bulk_create(new_items, batch_size=500)
        if changed_items:
            MarketSymbol.objects.bulk_update(changed_items, fields=SYNC_FIELDS, batch_size=500)
        inactive = MarketSymbol.objects.filter(
            market=snapshot.market,
            provider=snapshot.provider,
            active=True,
        ).exclude(code__in=codes)
        inactive_count = inactive.update(active=False, catalog_updated_at=now)
    return {
        "read": len(symbols),
        "added": added,
        "updated": updated,
        "inactive": inactive_count,
        "market_cap": len(snapshot.market_caps),
        "market_cap_error": snapshot.market_cap_error,
    }
