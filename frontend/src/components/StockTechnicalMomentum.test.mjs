import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const app = readFileSync(new URL('../App.vue', import.meta.url), 'utf8')
const momentum = readFileSync(new URL('./StockTechnicalMomentum.vue', import.meta.url), 'utf8')
const fear = readFileSync(new URL('./StockFearGreed.vue', import.meta.url), 'utf8')
const languages = readFileSync(new URL('../i18n.js', import.meta.url), 'utf8')

const chart = app.indexOf('<MarketChart v-if="selectedSymbol"')
const wrapper = app.indexOf('<div v-if="selectedSymbol" class="stock-analysis-panels">')
const fearPanel = app.indexOf('<StockFearGreed :key=')
const momentumPanel = app.indexOf('<StockTechnicalMomentum :key=')
const disclaimer = app.indexOf("<footer>{{ t('disclaimer') }}</footer>")
assert.ok(chart >= 0 && chart < wrapper && wrapper < fearPanel &&
  fearPanel < momentumPanel && momentumPanel < disclaimer,
  'Both panels must follow complete chart panes and precede disclaimer')
for (const term of ['grid-template-columns:repeat(2,minmax(0,1fr))',
  '@media(max-width:900px)', 'StockTechnicalMomentum']) {
  assert.ok(app.includes(term), `Layout contract missing: ${term}`)
}
for (const term of ['/api/stock-technical-momentum/', 'controller?.abort()',
  'request !== generation', "data.period !== '1d'", 'data.dimensions.length !== 6',
  'result.value?.signal', "state === 'ready' && result"]) {
  assert.ok(momentum.includes(term), `Momentum contract missing: ${term}`)
}
assert.ok(!/Math.random|mockScore|fakeScore|iframe/i.test(momentum))
assert.ok(fear.includes('/api/stock-fear-greed/'), 'Accepted sentiment panel retained')
for (const key of ['tmTitle', 'tmDaily', 'tmLoading', 'tmUnavailable', 'tmInsufficient',
  'tmTrend', 'tmBias', 'tmVolume', 'tmSupport', 'tmMacd', 'tmRsi',
  'tmStrongBuy', 'tmBuy', 'tmWatch', 'tmSell', 'tmStrongSell']) {
  assert.equal(languages.split(key + ':').length - 1, 6,
    `Exactly six language translations required for ${key}`)
}
console.log('V1.1.12 technical momentum UI contract: PASS')
