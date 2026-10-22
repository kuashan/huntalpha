import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const globalCss = readFileSync(new URL('./style.css', import.meta.url), 'utf8')
const app = readFileSync(new URL('./App.vue', import.meta.url), 'utf8')
const links = app.match(/<nav>(.*?)<\/nav>/s)?.[1] ?? ''

assert.equal((links.match(/<a\b/g) || []).length, 4, 'header must retain four nav entries')
for (const key of ['market', 'watchlist', 'strategy', 'news']) {
  assert.ok(links.includes(`t('${key}')`), `missing navigation entry: ${key}`)
}
assert.doesNotMatch(globalCss, /nav\s+a:not\(\.active\)\s*\{\s*display\s*:\s*none/i)
assert.match(globalCss, /@media\(max-width:800px\)/)
assert.match(app, /\.terminal > header\{flex-wrap:nowrap/)
assert.match(app, /\.terminal > header nav\{display:flex;flex:1 1 auto/)
assert.match(app, /\.terminal > header nav a\{display:grid/)
assert.match(app, /@media\(max-width:380px\)/)
assert.match(app, /\.terminal > header \.brand-name\{display:none\}/)
assert.doesNotMatch(app, /\.terminal > header nav[^\n]*overflow-x\s*:\s*auto/)
console.log('V1.1.8 mobile single-row navigation contract: PASS')
