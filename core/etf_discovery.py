"""On-demand ETF discovery against verified Yahoo Finance instrument metadata.

This is a *catalog identity* source, never a quote/candle fallback. Yahoo can
classify mainland China ETFs as EQUITY; their supplied long names must still
explicitly say ETF before we accept them. A real ETF must be verified again
when an account asks to save it to its watchlist.
"""
from __future__ import annotations

import hashlib
import json
import re
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from django.core.cache import cache


_SEARCH_URL = "https://query1.finance.yahoo.com/v1/finance/search"
_MAX_BYTES = 256 * 1024
_ETF_NAME = re.compile(r"\bETF\b", re.IGNORECASE)


class ETFDiscoveryUnavailable(RuntimeError):
    pass


def _search_query(query: str) -> str | None:
    candidate = str(query or "").strip()
    if not 2 <= len(candidate) <= 40:
        return None
    if re.fullmatch(r"(?:SH|SZ)\.\d{6}", candidate, re.IGNORECASE):
        prefix, number = candidate.upper().split(".")
        return f"{number}.{'SS' if prefix == 'SH' else 'SZ'}"
    if re.fullmatch(r"HK\.\d{1,5}", candidate, re.IGNORECASE):
        return f"{int(candidate.split('.')[1]):04d}.HK"
    if re.fullmatch(r"US\.[A-Z][A-Z0-9.\-]{0,11}", candidate, re.IGNORECASE):
        return candidate.split(".", 1)[1].upper()
    if (
        "ETF" in candidate.upper() or "基金" in candidate
        or re.fullmatch(r"\d{6}|\d{4}", candidate)
        or re.fullmatch(r"[A-Za-z]{2,4}", candidate)
    ):
        return candidate
    return None


def _record(quote):
    if not isinstance(quote, dict):
        return None
    symbol = str(quote.get("symbol") or "").strip().upper()
    kind = str(quote.get("quoteType") or "").upper()
    short_name = str(quote.get("shortname") or "").strip()
    long_name = str(quote.get("longname") or "").strip()
    if len(long_name) > 160 or len(short_name) > 160:
        return None
    if symbol.endswith(".SS") or symbol.endswith(".SZ"):
        body, suffix = symbol.rsplit(".", 1)
        if not re.fullmatch(r"\d{6}", body):
            return None
        # Yahoo describes Shanghai/Shenzhen ETFs as EQUITY. Never infer
        # fund identity from a numeric ticker prefix alone.
        if kind not in {"ETF", "EQUITY"} or not _ETF_NAME.search(long_name + " " + short_name):
            return None
        code, market = f"{'SH' if suffix == 'SS' else 'SZ'}.{body}", "cn"
    elif symbol.endswith(".HK"):
        body = symbol[:-3]
        if not re.fullmatch(r"\d{1,5}", body) or kind != "ETF":
            return None
        code, market = f"HK.{int(body):05d}", "hk"
    elif re.fullmatch(r"[A-Z][A-Z0-9.\-]{0,11}", symbol) and kind == "ETF":
        code, market = f"US.{symbol}", "us"
    else:
        return None
    name = long_name or short_name
    if not name:
        return None
    return {
        "code": code, "name": name, "market": market,
        "exchange": str(quote.get("exchange") or market.upper())[:32],
        "security_type": "ETF", "active": True,
        "provider": "yahoo-finance",
        "provider_symbol": symbol,
    }


def discover_etfs(query: str) -> tuple[dict, ...]:
    """Read-only lookup with a bounded request, result count and TTL cache."""
    vendor_query = _search_query(query)
    if vendor_query is None:
        return ()
    key = "etf-discovery-v1:" + hashlib.sha256(vendor_query.upper().encode("utf-8")).hexdigest()
    cached = cache.get(key)
    if cached is not None:
        return tuple(cached)
    url = _SEARCH_URL + "?" + urlencode({"q": vendor_query, "quotesCount": 20, "newsCount": 0})
    request = Request(url, headers={"User-Agent": "Mozilla/5.0 (SiftAlpha ETF lookup)", "Accept": "application/json"})
    try:
        with urlopen(request, timeout=6) as response:
            raw = response.read(_MAX_BYTES + 1)
        if len(raw) > _MAX_BYTES:
            raise ETFDiscoveryUnavailable("ETF 证券目录响应超出上限")
        quotes = json.loads(raw).get("quotes")
        if not isinstance(quotes, list):
            raise ETFDiscoveryUnavailable("ETF 证券目录格式异常")
    except (HTTPError, URLError, TimeoutError, OSError, ValueError, UnicodeError) as exc:
        raise ETFDiscoveryUnavailable("ETF 证券目录暂不可用") from exc
    result = {}
    for quote in quotes[:20]:
        row = _record(quote)
        if row is not None:
            result.setdefault(row["code"], row)
    records = tuple(result.values())
    cache.set(key, records, timeout=300)
    return records


def lookup_etf(code: str) -> dict | None:
    """Fail closed: a watchlist item requires an exact verified vendor code."""
    normalized = str(code or "").strip().upper()
    if not re.fullmatch(r"(?:SH|SZ)\.\d{6}|HK\.\d{1,5}|US\.[A-Z][A-Z0-9.\-]{0,11}", normalized):
        return None
    for record in discover_etfs(normalized):
        if record["code"] == normalized:
            return record
        if record["market"] == "hk" and normalized.startswith("HK.") and (
            int(record["code"].split(".")[1]) == int(normalized.split(".")[1])
        ):
            return record
    return None
