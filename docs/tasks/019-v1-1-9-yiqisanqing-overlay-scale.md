# V1.1.9 — Restore Yi Qi San Qing graphics while hiding right-side numbers

## Incident

- V1.1.7 introduced `chart.priceScale('right', pane).applyOptions({ visible: false })` for the sub-pane named `一气三清`.
- The production V1.1.8 release inherited this code, and the user reported that the **entire indicator vanished**, not only the numeric price axis.
- Production was safely rolled back using `siftalpha-web-admin rollback` to the previously accepted V1.1.6 image `sha256:0b2616ff69e4d574c7ef28e9e5dc67e153013a078b648c5e945812518c7f6e0d`. The live database was retained.

## Minimal fix

- **Do not disable a scale used by plotted series and custom primitives.**
- For the `一气三清` sub-indicator only, use the library's *hidden overlay price scale* (`priceScaleId` other than `right` and `left`). This keeps `priceToCoordinate()` usable for the formula's STICKLINE and DRAWTEXT primitives and hides its numeric axis.
- Both explicitly plotted line series and the invisible anchor series used for stick/text drawing must share the same overlay scale. Other indicators/main chart stay on the normal right axis.
- Remove the V1.1.7 `syncSubPanePriceAxes()` routine; do not touch formula source, calculations, drawing data, provider selection or other UI.
- Update the chart contract to check the overlay binding and *forbid* the prior `visible:false` direct right-axis mutation.
- V1.1.9 retains the V1.1.8 mobile one-row navigation and header realtime status changes.

## Release

The existing release-branch GitHub Actions workflow performs frontend/chart tests, Vite build, Django checks, ARM64 container build and immutable BuildKit provenance verification. A passing static test/build does **not** prove a visual regression is fixed; the user must verify the indicator graph on a real browser before this version is accepted as a production baseline.

**Never auto-deploy**. Production stays on V1.1.6 until an independent, immutable GHCR Digest is available and the user explicitly authorizes the specific candidate after reviewing this incident.
