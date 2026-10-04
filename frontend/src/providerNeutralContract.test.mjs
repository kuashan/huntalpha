import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

const root = dirname(fileURLToPath(import.meta.url))
const app = readFileSync(join(root, 'App.vue'), 'utf8')
const chart = readFileSync(join(root, 'components', 'MarketChart.vue'), 'utf8')

assert.ok(app.includes('source') && app.includes('status'))
assert.ok(!app.includes("'futu-opend': '富途 OpenD'"))
assert.ok(!chart.includes("props.symbol.market === 'crypto' ? 'Coinbase' : '富途 OpenD'"))
