# Task 020 — SiftAlpha.com V1.1.10 stock selection consistency

Status: IMPLEMENTED — pending GitHub Actions and real-browser acceptance.
Base: formal source branch `release/siftalpha-web-v1`, starting commit `e693a77b4fc5f48d5b1eaf6841ddbc06811c7500` (V1.1.9).

## Observed problem

When rapidly selecting instruments across Chinese A-shares, Hong Kong and US markets, the displayed name, current quote and K-line can temporarily disagree. Existing UI binds title to `selected`, quote to `quotes[selected.code]`, and the chart to a separate asynchronous `MarketChart` draw queue. The old watchlist-quote batch waited for all symbols to resolve before writing, and clicking a symbol did not refresh its quote. Old chart work could complete after a new selection.

These are code-level risk paths, not a claim that a logged-in browser reproduction was performed.

## Approved minimal scope

1. Route all current-quote refreshes through a tiny per-symbol request coordinator. Preserve individual results as they arrive, ensure the most recent request for each symbol wins, validate provider response identity when returned, clear stale price while loading a freshly selected symbol, and ignore replies after sign-out or unmount. Preserve watchlist quote isolation on search/list updates.
2. Key `MarketChart` by `selected.code` so old symbol charts are dismantled when selection changes; invalidate any outstanding asynchronous drawing generations when the old chart unmounts.
3. Retain name and code from the same clicked `MarketSymbol` catalog row. Existing market switching and period behavior remains unchanged.
4. Add executable Node regression covering out-of-order multi-market requests, stale old quote, re-selecting a symbol, mismatched provider symbol, dropped search-list rows, and post-sign-out replies. Run in release workflow alongside existing chart tests.
5. Bump footer and OCI/GHCR release tag to **V1.1.10**, retain SHA256, source commit, BuildKit provenance and Linux ARM64 release checks.

## Explicit exclusions

- No new true realtime quote subscription or polling cadence changes. This remains a separate product decision and depends on data-source permissions.
- No K-line count, history pagination, provider priority, indicator formulas or performance optimization.
- No Python, migrations, database, account tier, user workspace, Cloudflare or other container changes.
- No synthetic prices or fake fallback.
- No production deployment without explicit user authorization of the immutable V1.1.10 image Digest.

## Acceptance boundary

GitHub Actions passing is **code/build validation**, not a claim that authenticated production UI has been manually verified. After authorized deployment, verify rapid switching among A/HK/US watchlist symbols and that the header code, quote, chart candles and indicator rendering correspond to the chosen symbol, even with slow or unavailable quotes. User is final acceptance authority.
