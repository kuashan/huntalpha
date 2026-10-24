import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { resolveSelectedSymbol } from './symbolSelection.mjs'

// Reported regression: HK.00772 was highlighted as 阅文集团, but the main
// heading displayed 焦点科技 combined with the HK code.
const catalog = [
  { code: 'SZ.002315', name: '焦点科技', market: 'cn' },
  { code: 'HK.00772', name: '阅文集团', market: 'hk' },
  { code: 'US.ORCL', name: '甲骨文', market: 'us' },
]
const stale = { code: 'HK.00772', name: '焦点科技', market: 'cn' }
const corrected = resolveSelectedSymbol(stale, catalog)
assert.deepEqual(corrected, { code: 'HK.00772', name: '阅文集团', market: 'hk' })
assert.deepEqual(stale, { code: 'HK.00772', name: '焦点科技', market: 'cn' }, 'do not mutate selection')
assert.notEqual(corrected, catalog[1], 'do not mutate catalog rows through selected state')

// Switching rapidly only takes metadata from the corresponding code, even
// when the catalog is delayed, reordered or the incoming code casing differs.
assert.equal(resolveSelectedSymbol({ code: 'sz.002315', name: '旧名称' }, catalog).name, '焦点科技')
assert.equal(resolveSelectedSymbol({ code: 'US.ORCL', name: '旧名称' }, [...catalog].reverse()).name, '甲骨文')
assert.equal(resolveSelectedSymbol({ code: 'HK.00772', name: '阅文集团' }, [catalog[0]])?.name, '阅文集团')
assert.equal(resolveSelectedSymbol(null, catalog), null)

const app = readFileSync(new URL('../App.vue', import.meta.url), 'utf8')
assert.match(app, /const selectedSymbol = computed\(\(\) => resolveSelectedSymbol\(selected\.value, symbols\.value\)\)/)
assert.match(app, /const selectedQuote = computed\(\(\) => quotes\.value\[String\(selectedSymbol\.value\?\.code/)
assert.match(app, /<h1 :key="`\$\{selectedSymbol\?\.code[^"]+"[\s\S]*?\{\{ selectedSymbol\?\.name/)
assert.match(app, /<MarketChart v-if="selectedSymbol" :key="selectedSymbol\.code" :symbol="selectedSymbol"/)
for (const panel of ['StockFearGreed', 'StockTechnicalMomentum']) {
  assert.match(app, new RegExp('<' + panel + ' :key="[^"]+selectedSymbol\\.code" :symbol="selectedSymbol"'))
}
assert.doesNotMatch(app, /<h1[^>]*>\{\{ selected\?\.name/)
console.log('V2.0.0 stock name/code/chart/panel consistency: PASS')
