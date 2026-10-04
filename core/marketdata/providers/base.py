class MarketDataProviderError(RuntimeError):
    """Explicit provider/configuration failure; never a fake-data fallback."""

    def __init__(self, message, *, status="unavailable"):
        super().__init__(message)
        self.status = status


def unavailable_status(provider_id: str, *, reason: str, detail: str | None = None) -> dict:
    payload = {"status": reason, "provider": provider_id, "mode": "unavailable"}
    if detail:
        payload["detail"] = detail
    return payload
