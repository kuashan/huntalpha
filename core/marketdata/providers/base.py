class MarketDataProviderError(RuntimeError):
    """Explicit provider/configuration failure; never a fake-data fallback."""


def unavailable_status(provider_id: str, *, reason: str, detail: str | None = None) -> dict:
    payload = {"status": reason, "provider": provider_id, "mode": "unavailable"}
    if detail:
        payload["detail"] = detail
    return payload
