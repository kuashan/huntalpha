# V1.1.7 — Chart presentation-only adjustments

## Approved scope (2026-10-22)

Baseline: accepted V1.1.6, commit `9a5e0122dfcf1ae54662b6dfa5b7610b7718f1b6`.

1. For the sub-indicator named `一气三清`, hide its own right-hand numeric price scale only. Other sub-panes and the main price scale keep their labels. Removing and adding indicators re-evaluates the pane visibility; the chart data and formula calculation are unchanged. The usual long-press/hover crosshair can reveal the underlying series value without reserving axis width.
2. Relocate the existing realtime status text (including non-live, delayed, reconnecting and unavailable states) from the upper-right of the chart to immediately after the `主图：...` heading. No change to SSE, realtime detection, timestamps or provider selection.
3. Increment the displayed footer and immutable ARM64 image tag/OCI version to **V1.1.7**. Keep all production release guardrails unchanged.

## Tests and release boundary

- Add the chart presentation contract to `npm run test:chart`; preserve existing chart, realtime, indicators, workspace and footer checks, followed by `npm run build`.
- GitHub Actions release workflow must continue to run all backend checks, frontend tests, ARM64 Linux image build and BuildKit provenance verification after merge to `release/siftalpha-web-v1`.
- **This PR does not deploy** and does not update the currently accepted V1.1.6 production baseline. Production deployment requires user authorization of the exact resulting GHCR SHA-256 Digest.
- No Python, database migration, indicators/formula sources, quotes, membership, account, Cloudflare, Crypto or Options Monitor modifications.
