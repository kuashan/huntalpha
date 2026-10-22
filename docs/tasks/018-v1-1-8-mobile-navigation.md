# V1.1.8 — Mobile header single-row navigation

## Confirmed root cause

The approved V1.1.7 frontend had an explicit rule in `frontend/src/style.css` at `max-width:800px`: `.feed,nav a:not(.active){display:none}`. It intentionally hid 自选、策略、资讯 on phones. This was not evidence that the viewport cannot fit the labels.

## Approved minimal change

- Remove only the `nav a:not(.active){display:none}` part; preserve the existing mobile feed treatment.
- Keep Logo/brand, four existing navigation labels and the PRO/language controls on **one header row** via responsive spacing, flex allocation and slightly smaller fonts.
- At extremely narrow widths (max 380px), omit only the brand wordmark, retaining the logo and all four navigation items. No horizontal scrolling, two-line header or extra menu.
- Preserve the currently implemented navigation behavior; the inactive items are existing placeholders, not new page implementations.
- Bump site footer and ARM64 image tag/OCI version to V1.1.8.

## Testing and boundaries

- Add a static contract to verify that all four menu labels remain present, the mobile hide rule is absent, and narrow mobile layouts remain single-row.
- Run existing frontend tests, `node src/mobileNavigation.test.mjs`, and full Vite build in the release GitHub Actions ARM64 workflow.
- Do not alter API, existing indicator calculations, account/workspace state, membership, database/migrations, Crypto, Cloudflare or other containers.
- Production is **not** auto-deployed; collect an immutable GHCR SHA256 digest and obtain separate explicit user authorization for `siftalpha-web-admin` preflight/deploy.
