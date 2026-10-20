import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const root = dirname(fileURLToPath(import.meta.url))
const app = readFileSync(join(root, 'App.vue'), 'utf8')
const i18n = readFileSync(join(root, 'i18n.js'), 'utf8')

assert.match(app, /const watchlistExpanded = ref\(true\)/)
assert.ok(app.includes("'watchlist-collapsed': !watchlistExpanded"))
assert.ok(app.includes('aria-controls="watchlist-contents"'))
assert.ok(app.includes(':aria-expanded="watchlistExpanded"'))
assert.ok(app.includes('@click="watchlistExpanded = !watchlistExpanded"'))
assert.ok(app.includes('v-show="watchlistExpanded" id="watchlist-contents"'))
assert.ok(app.includes('.workspace.watchlist-collapsed{grid-template-columns:72px minmax(0,1fr)}'))
assert.ok(app.includes('@media(max-width:800px){.workspace.watchlist-collapsed'))
assert.ok(app.includes('@click.stop="toggleWatchlist(item)"'))
assert.ok(app.includes('@click="selectSymbol(item)"'))
assert.ok(app.includes("const endpoint = search ? 'symbol-search/' : 'watchlist/'"))
assert.ok(i18n.includes("watchlistExpand: '展开'"))
assert.ok(i18n.includes("watchlistCollapse: '收起'"))

assert.ok(app.includes('return dataStatus'))
assert.ok(!app.includes("t('quoteSource')"))
assert.ok(!app.includes('providerLabel'))
assert.ok(!app.includes('Yahoo Finance'))
assert.ok(!app.includes("<small>{{ item.code === 'crypto' ? 'Coinbase' : '统一行情源' }}</small>"))
assert.ok(app.includes('refreshQuotes(items)'))
console.log('Watchlist disclosure and provider-label hiding: PASS')
