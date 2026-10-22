import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

// Keep these presentation-only changes scoped to the named sub-pane.
// They must never alter formula calculations, data routing, or other panes.
const chart = readFileSync(new URL('../components/MarketChart.vue', import.meta.url), 'utf8')
const app = readFileSync(new URL('../App.vue', import.meta.url), 'utf8')

assert.match(chart, /const hideYiQiSanQingAxis = item => item\?\.placement === 'sub'.*'一气三清'/)
assert.match(chart, /chart\.priceScale\('right', pane\)\.applyOptions\(\{ visible: !hideYiQiSanQingAxis\(result\.item\) \}\)/)
assert.equal((chart.match(/syncSubPanePriceAxes\(\)/g) || []).length, 3, 'initial and dynamic panes must refresh axis visibility')
assert.match(chart, /chart\.subscribeCrosshairMove\(updateHiddenSubCrosshairValue\)/)
assert.match(chart, /param\.paneIndex/)
assert.match(chart, /param\.seriesData\.get\(series\)/)
assert.match(chart, /v-if="hiddenSubCrosshairValue"/)

assert.match(chart, /<Teleport to="#market-chart-status-host">/)
assert.equal((chart.match(/class="realtime-status"/g) || []).length, 1, 'show realtime state once')
assert.match(chart, /\{\{ realtimeStatusText \}\}/)
assert.match(app, /class="chart-main-heading"[^>]*>\{\{ t\('main'\) \}\}.*id="market-chart-status-host"/)
assert.equal((app.match(/id="market-chart-status-host"/g) || []).length, 1, 'single target after main heading')
assert.match(app, /\.chart-main-heading\{display:inline-flex;align-items:center;gap:8px/)
console.log('V1.1.7 chart presentation contract: PASS')
