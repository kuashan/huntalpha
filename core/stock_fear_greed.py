"""Read-only adapter for the separately operated iwanlebron/stock-analysis service.

No score formulas or upstream implementation are copied into SiftAlpha.
"""
import json
import math
import os
import re
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen


class FearGreedUnavailable(Exception):
    def __init__(self, status):
        self.status = status
        super().__init__(status)


def provider_ticker(code):
    """Map a verified SiftAlpha catalog symbol to Yahoo-style upstream ticker."""
    code = str(code or "").strip().upper()
    if re.fullmatch(r"US\.[A-Z][A-Z0-9.\-]{0,19}", code):
        return code[3:]
    if re.fullmatch(r"SH\.\d{6}", code):
        return code[3:] + ".SS"
    if re.fullmatch(r"SZ\.\d{6}", code):
        return code[3:] + ".SZ"
    if re.fullmatch(r"HK\.\d{1,5}", code):
        return code[3:].lstrip("0").zfill(4) + ".HK"
    if re.fullmatch(r"CC\.[A-Z0-9]{2,15}[-/][A-Z0-9]{2,15}", code):
        return code[3:].replace("/", "-")
    if re.fullmatch(r"CC\.[A-Z0-9]{2,15}(USD|USDT)", code):
        currency = "USDT" if code.endswith("USDT") else "USD"
        return code[3:-len(currency)] + "-" + currency
    raise FearGreedUnavailable("unsupported_symbol")


def fetch_stock_fear_greed(code, *, service_url=None):
    """Fetch only pre-calculated upstream results, never compute a local score."""
    base = (service_url if service_url is not None else
            os.environ.get("SIFTALPHA_STOCK_FEAR_GREED_URL", "")).strip().rstrip("/")
    if not base:
        raise FearGreedUnavailable("not_configured")
    parsed = urlsplit(base)
    if (parsed.scheme not in ("http", "https") or not parsed.hostname or
            parsed.username or parsed.password or parsed.query or parsed.fragment or
            parsed.path not in ("", "/")):
        raise FearGreedUnavailable("invalid_configuration")

    ticker = provider_ticker(code)
    query = urlencode({"ticker": ticker, "freq": "1d", "window": 252, "lang": "zh", "tail": 30})
    request = Request(base + "/fear-greed?" + query, headers={"Accept": "application/json"})
    try:
        with urlopen(request, timeout=7) as response:
            raw = response.read(1024 * 1024 + 1)
        if len(raw) > 1024 * 1024:
            raise FearGreedUnavailable("invalid_response")
        payload = json.loads(raw)
    except (HTTPError, URLError, TimeoutError, OSError):
        raise FearGreedUnavailable("upstream_unavailable")
    except (UnicodeError, ValueError, TypeError):
        raise FearGreedUnavailable("invalid_response")

    if not isinstance(payload, dict) or str(payload.get("ticker", "")).upper() != ticker.upper():
        raise FearGreedUnavailable("invalid_response")
    latest = payload.get("latest")
    if not isinstance(latest, dict):
        raise FearGreedUnavailable("no_score")
    score = latest.get("score")
    if isinstance(score, bool) or not isinstance(score, (int, float)) or not math.isfinite(score) or not 0 <= score <= 100:
        raise FearGreedUnavailable("no_score")
    date = latest.get("date")
    if not isinstance(date, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date):
        raise FearGreedUnavailable("invalid_response")

    subscores = {}
    if isinstance(payload.get("latest_subscores"), dict):
        for key in ("trend", "momentum", "rsi", "macd", "drawdown", "volatility", "mfi", "bb_pct_b"):
            value = payload["latest_subscores"].get(key)
            if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and 0 <= value <= 100:
                subscores[key] = round(float(value), 2)

    label = latest.get("label")
    if not isinstance(label, str) or len(label) > 40:
        label = ""
    return {
        "code": code.upper(),
        "ticker": ticker,
        "source": "iwanlebron/stock-analysis",
        "period": "1d",
        "score": round(float(score), 2),
        "label": label,
        "date": date,
        "subscores": subscores,
        "status": "ready",
    }
