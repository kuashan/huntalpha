"""Persisted global market-source choices; auto preserves the V1.1.4 routing order."""

PROFILE_TO_MARKET = {
    "US_EQUITY": "us",
    "CN_A_SHARE": "cn",
    "HK_EQUITY": "hk",
    "CRYPTO": "crypto",
}

PROVIDERS_BY_MARKET = {
    "us": ("auto", "yahoo-finance", "tencent-public", "longbridge"),
    "cn": ("auto", "yahoo-finance", "tencent-public", "tushare", "longbridge"),
    "hk": ("auto", "yahoo-finance", "tencent-public", "longbridge"),
    "crypto": ("auto", "coinbase"),
}

PROVIDER_LABELS = {
    "auto": "自动选择（沿用当前优先级与备用来源）",
    "yahoo-finance": "Yahoo Finance",
    "tencent-public": "腾讯财经",
    "tushare": "Tushare",
    "longbridge": "Longbridge",
    "coinbase": "Coinbase",
}


def selected_provider(market_id: str) -> str:
    """Look up the latest administrator choice at request time.

    No record means auto: upgrades retain the existing production behavior.
    Never fall back to another provider on an invalid persisted setting.
    """
    market = PROFILE_TO_MARKET.get(str(market_id).upper())
    if market is None:
        return "auto"
    from core.models import MarketDataSourceSetting

    provider = MarketDataSourceSetting.objects.filter(pk=market).values_list("provider", flat=True).first()
    if provider is None:
        return "auto"
    if provider not in PROVIDERS_BY_MARKET[market]:
        raise ValueError(f"invalid stored market provider for {market}")
    return provider
