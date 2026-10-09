from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class MarketProfile:
    """Market rules independent from any data provider."""

    market_id: str
    label_zh: str
    timezone: str
    continuous: bool
    sessions: tuple[tuple[str, str], ...] = ()


CRYPTO_24_7 = MarketProfile(
    market_id="CRYPTO",
    label_zh="加密货币",
    timezone="UTC",
    continuous=True,
)

US_EQUITY = MarketProfile(
    market_id="US_EQUITY",
    label_zh="美股",
    timezone="America/New_York",
    continuous=False,
    sessions=(("09:30", "16:00"),),
)

CN_A_SHARE = MarketProfile(
    market_id="CN_A_SHARE",
    label_zh="中国 A 股",
    timezone="Asia/Shanghai",
    continuous=False,
    sessions=(("09:30", "11:30"), ("13:00", "15:00")),
)

HK_EQUITY = MarketProfile(
    market_id="HK_EQUITY",
    label_zh="港股",
    timezone="Asia/Hong_Kong",
    continuous=False,
    # Normal continuous trading sessions. Auction phases are not silently
    # treated as ordinary bars and can be added as explicit capabilities later.
    sessions=(("09:30", "12:00"), ("13:00", "16:00")),
)


MARKET_PROFILES = {
    profile.market_id: profile
    for profile in (CRYPTO_24_7, US_EQUITY, CN_A_SHARE, HK_EQUITY)
}


def normalize_market_id(value: str) -> str:
    return str(value or "").strip().upper()


def profile_for(value: str) -> MarketProfile:
    market_id = normalize_market_id(value)
    try:
        return MARKET_PROFILES[market_id]
    except KeyError as exc:
        raise KeyError(f"unsupported market profile: {market_id}") from exc
