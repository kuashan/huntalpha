import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { hiddenIndicatorScaleId } from '../indicators/priceScalePolicy.mjs'

// Keep these presentation-only changes scoped to the named sub-pane.
// They must never alter formula calculations, data routing, or other panes.
const chart = readFileSync(new URL('../components/MarketChart.vue', import.meta.url), 'utf8')
const app = readFileSync(new URL('../App.vue', import.meta.url), 'utf8')

// An invisible *overlay* scale retains price-to-coordinate mappings for
// custom STICKLINE and text primitives. Never disable their active price axis.
assert.equal(hiddenIndicatorScaleId({ name: '一气三清', code: 'YQS', placement: 'sub' }), 'yi-qi-san-qing-YQS')
assert.equal(hiddenIndicatorScaleId({ name: '一气 三清', code: 'YQS', placement: 'sub' }), 'yi-qi-san-qing-YQS')
assert.equal(hiddenIndicatorScaleId({ name: '一气三清', code: 'YQS', placement: 'main' }), undefined)
assert.equal(hiddenIndicatorScaleId({ name: 'MACD', code: 'MACD', placement: 'sub' }), undefined)
assert.notEqual(hiddenIndicatorScaleId({ name: '一气三清', code: 'A', placement: 'sub' }), hiddenIndicatorScaleId({ name: '一气三清', code: 'B', placement: 'sub' }))
assert.match(chart, /const priceScaleId = hiddenIndicatorScaleId\(result\.item\)/)
assert.match(chart, /item\.width, priceScaleId\)\)/)
assert.match(chart, /addFormulaAnchor\(result\.drawing, pane, priceScaleId\)/)
assert.match(chart, /function addLine\(color, data, pane, style = 'solid', width = 1, priceScaleId\)/)
assert.match(chart, /function addFormulaAnchor\(drawing, pane, priceScaleId\)/)
assert.equal((chart.match(/\.\.\.\(priceScaleId \? \{ priceScaleId \} : \{\}\)/g) || []).length, 2, 'both visible lines and invisible primitive anchor must use overlay scale')
assert.match(chart, /anchor: layerAnchor/)
assert.match(chart, /new TongdaxinStickPrimitive\(chart, anchor, groups/)
assert.doesNotMatch(chart, /syncSubPanePriceAxes/)
assert.doesNotMatch(chart, /chart\.priceScale\('right', pane\)\.applyOptions/)
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
console.log('V1.1.9 hidden overlay price scale + presentation contract: PASS')
