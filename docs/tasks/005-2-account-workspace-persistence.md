# Task 005.2 — Account-global chart workspace persistence

Status: `IMPLEMENTED / PENDING_REVIEW` (not merged, not deployed).
Scope approved by user after 2026-10-19 V1.0.0 freeze.

## Confirmed behavior

- One global list of main and sub indicator IDs per authenticated account, reused across every market, symbol and candle period. Preserve list order and the current maximum of three sub indicators.
- Preserve active sub-chart heights (90–800 pixels) per account. Do **not** import old browser `localStorage` heights for authenticated accounts; first use defaults.
- Auto-save after indicators change (~650 ms debounce) and after a user finishes resizing panes. No save button, workspaces, templates, drawing tools, indicator tuning, cost profiles or new market features.
- Restore on login and across devices; transient load/write failures never replace previously valid server state. Show a localized sync failure message.
- Visitor retains temporary indicator use and the existing local-only height behavior.
- **Irreversible downgrade:** on FREE downgrade, remove saved indicators the account cannot use, not merely hide them. Re-upgrading PRO does not restore removed codes. Backend always enforces permissions on both read/write, regardless of stale client state. Disabled/unregistered formulas are pruned similarly.
- No formula source, calculated indicators, quote/K-line data, screen coordinates or user research notes are stored.
- Existing account preferences, FREE/PRO entitlement definitions, watchlist, formulas, markets and realtime calculation remain unchanged.

## Implementation and DB safety

- New OneToOne `AccountWorkspace`, additive `core.0013_accountworkspace` migration. Existing account and Formula tables untouched.
- Endpoint `GET/PUT /api/account/workspace/` authenticated only. CSRF remains required for PUT. Server validates input shape, heights, placement, active formula list and real member tier.
- Production release must separately authorize a DB backup/restore rehearsal and the migration guard review; **no migration or deployment has been performed**.
- V1.0.0 frozen release reference remains untouched. New code requires a new release version before any production publishing (Issue #48).

## Acceptance

1. FREE account remembers MA+MACD and pane heights on reload, across browsers, stocks and periods.
2. PRO account remembers CHANLUN/private Formula; downgrading to FREE immediately removes restricted codes permanently. Invalid/disabled ones cannot be saved even through direct API calls.
3. Different accounts cannot read each other's configurations; visitor cannot persist.
4. Invalid writes and network failures do not erase a stored configuration; empty deliberate selection persists.
5. Confirm migration creates only its new isolated table and preserves synthetic baseline account, member tier, watchlist and four Formula source records.
6. Django full tests, schema check, frontend unit tests and production build all pass in PR CI before requesting merge/deployment approval.

## Excluded

No chart algorithm change, no new drawing/cost features, no layout/template management, no DB or production-server operation, no Cloudflare change.
