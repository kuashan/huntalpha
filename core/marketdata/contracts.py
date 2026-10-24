from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Protocol

from .calendar import canonical_calendar_bar, canonical_calendar_rows
from .profiles import MarketProfile


@dataclass(frozen=True)
class MarketDataFetch:
    """A complete provider window with forming bars kept separate."""

    market_id: str
    provider_id: str
    provider_label_zh: str
    symbol: str
    timeframe: str
    completed: list[Any] = field(default_factory=list)
    forming: Any | None = None
    meta: dict[str, Any] = field(default_factory=dict)
    stream_url: str | None = None

    @property
    def rows(self) -> list[Any]:
        """Compatibility view for SLTD-style callers."""
        return list(self.completed)

    @classmethod
    def from_payload(
        cls,
        *,
        market_id: str,
        provider_id: str,
        provider_label_zh: str,
        symbol: str,
        timeframe: str,
        payload: Any,
        stream_url: str | None = None,
    ) -> "MarketDataFetch":
        if isinstance(payload, MarketDataFetch):
            return payload
        if isinstance(payload, dict):
            completed = payload.get("completed") or payload.get("rows") or []
            forming = payload.get("forming")
            meta = dict(payload.get("meta") or {})
        elif isinstance(payload, list):
            completed, forming, meta = payload, None, {}
        else:
            raise TypeError("provider payload is not a normalized market window")
        if not isinstance(completed, list):
            raise TypeError("provider completed bars are not a list")
        return cls(
            market_id=market_id,
            provider_id=provider_id,
            provider_label_zh=provider_label_zh,
            symbol=symbol,
            timeframe=timeframe,
            completed=canonical_calendar_rows(completed, market_id, timeframe),
            forming=canonical_calendar_bar(forming, market_id, timeframe),
            meta=meta,
            stream_url=stream_url,
        )


class MarketDataProvider(Protocol):
    provider_id: str
    provider_label_zh: str
    profile: MarketProfile

    def fetch_window(self, symbol: str, timeframe: str, **kwargs: Any) -> Any:
        ...

    def capabilities(self, market_id: str | None = None) -> dict[str, Any]:
        ...

    def status(self, market_id: str | None = None, symbol: str | None = None) -> dict[str, Any]:
        ...

    def list_securities(self, market_id: str, query: str = "", page: int = 1) -> Any:
        ...

    def quote(self, symbol: str) -> Any:
        ...

    def fetch_recent(self, symbol: str, timeframe: str, **kwargs: Any) -> Any:
        ...

    def subscribe(self, symbol: str, timeframe: str, callback: Callable[[Any], None]) -> Any:
        ...

    def unsubscribe(self, symbol: str, timeframe: str) -> Any:
        ...
