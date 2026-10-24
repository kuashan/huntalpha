import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const app = readFileSync(new URL('../App.vue', import.meta.url), 'utf8')
const momentum = readFileSync(new URL('./StockTechnicalMomentum.vue', import.meta.url), 'utf8')
const fear = readFileSync(new URL('./StockFearGreed.vue', import.meta.url), 'utf8')
const languages = readFileSync(new URL('../i18n.js', import.meta.url), 'utf8')

const chart = app.indexOf('<MarketChart v-if="selected"')
const wrapper = app.indexOf('<div v-if="selected" class="stock-analysis-panels">')
const fearPanel = app.indexOf('<StockFearGreed :key=')
const momentumPanel = app.indexOf('<StockTechnicalMomentum :key=')
const disclaimer = app.indexOf("<footer>{{ t('disclaimer') }}</footer>")
assert.ok(chart >= 0 && chart < wrapper && wrapper < fearPanel &&
  fearPanel < momentumPanel && momentumPanel < disclaimer,
  'Both panels must display below the complete chart and above disclaimer')
assert.match(app, /grid-template-columns:repeat\(2,minmax\(0,1fr\)\)/)
assert.match(app, /@media\(max-width:900px\)/)
assert.match(momentum, /\/api\/stock-technical-momentum\//)
assert.match(momentum, /controller\?\.abort\(\)/)
assert.match(momentum, /request !== generation/)
assert.match(momentum, /data.period !== '1d'/)
assert.match(momentum, /data.dimensions.length !== 6/)
assert.match(momentum, /result.value\\?\\.signal/)
assert.match(momentum, /state === 'ready' && result/)
assert.doesNotMatch(momentum, /Math.random|mockScore|fakeScore|iframe/i)
assert.match(fear, /\/api\/stock-fear-greed\//, 'existing module retained')
for (const key of ['tmTitle', 'tmDaily', 'tmLoading', 'tmUnavailable', 'tmInsufficient',
  'tmTrend', 'tmBias', 'tmVolume', 'tmSupport', 'tmMacd', 'tmRsi',
  'tmStrongBuy', 'tmBuy', 'tmWatch', 'tmSell', 'tmStrongSell']) {
  assert.equal((languages.match(new RegExp(key + ':', 'g')) || []).length, 6,
    `Expected exactly six translations for ${key}`)
}
console.log('V1.1.12 technical momentum UI contract: PASS')
