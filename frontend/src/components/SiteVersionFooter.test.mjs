import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const footer = readFileSync(new URL('./SiteVersionFooter.vue', import.meta.url), 'utf8')
const trading = readFileSync(new URL('../App.vue', import.meta.url), 'utf8')
const account = readFileSync(new URL('./PersonalCenter.vue', import.meta.url), 'utf8')

assert.match(footer, /const version = 'V1\.1\.9'/)
assert.match(footer, /<footer class="site-version-footer">SiftAlpha • \{\{ version \}\}<\/footer>/)
assert.doesNotMatch(footer, /<(a|button)\b/i)
assert.doesNotMatch(footer, /update.*(?:history|record)|changelog/i)

for (const [page, source] of [['terminal', trading], ['account', account]]) {
  assert.match(source, /import SiteVersionFooter from/)
  assert.equal((source.match(/<SiteVersionFooter\s*\/>/g) || []).length, 1, page)
  assert.doesNotMatch(source, /V1\.1\.9/, `${page} duplicates the version literal`)
}
console.log('Task 013 static contract: PASS (single value, two footers, no interactive changelog)')
