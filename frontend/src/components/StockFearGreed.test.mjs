import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const app = readFileSync(new URL('../App.vue', import.meta.url), 'utf8')
const panel = readFileSync(new URL('./StockFearGreed.vue', import.meta.url), 'utf8')
const i18n = readFileSync(new URL('../i18n.js', import.meta.url), 'utf8')

assert.match(app, /<StockFearGreed v-if="selected" :key="'fg:' \+ selected.code" :symbol="selected"\s*\/>/)
const chartIndex = app.indexOf('<MarketChart v-if="selected"')
const panelIndex = app.indexOf('<StockFearGreed :key="')
const footerIndex = app.indexOf("<footer>{{ t('disclaimer') }}</footer>")
assert.ok(chartIndex >= 0 && panelIndex > chartIndex && footerIndex > panelIndex,
  'Fear-greed panel must follow all chart panes and precede the page disclaimer')
assert.match(panel, /\/api\/stock-fear-greed\//)
assert.match(panel, /controller\?\.abort\(\)/)
assert.match(panel, /current !== generation/)
assert.match(panel, /String\(data.code\).toUpperCase\(\) !== code.toUpperCase\(\)/)
assert.match(panel, /data.period !== '1d'/)
assert.match(panel, /state === 'ready' && result/)
assert.match(panel, /fgNotConfigured/)
assert.doesNotMatch(panel, /Math.random|mockScore|fakeScore|iframe/i)

for (const language of ["'zh-CN'", "'zh-TW'", 'en:', 'ja:', 'ms:', 'fr:']) {
  assert.ok(i18n.includes(language), `Missing locale ${language}`)
}
for (const key of ['fgTitle', 'fgLoading', 'fgNotConfigured', 'fgNoScore', 'fgUnavailable',
  'fgExtremeFear', 'fgFear', 'fgNeutral', 'fgGreed', 'fgExtremeGreed']) {
  assert.equal((i18n.match(new RegExp(key + ':', 'g')) || []).length, 6, key)
}
console.log('V1.1.11 stock fear-greed static UI contract: PASS')
