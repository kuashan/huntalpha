import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { createQuoteCoordinator } from './quoteCoordinator.mjs'

const app = readFileSync(new URL('../App.vue', import.meta.url), 'utf8')
const chart = readFileSync(new URL('../components/MarketChart.vue', import.meta.url), 'utf8')
assert.match(app, /<MarketChart v-if="selected" :key="selected\.code" :symbol="selected"/)
assert.match(app, /selected\.value = item\s*\/\/[^\n]*\n[^\n]*\n\s*void quoteCoordinator\.refresh\(item\.code\)/)
assert.match(chart, /onBeforeUnmount\(\(\) => \{[\s\S]*?drawVersion \+= 1[\s\S]*?disconnectRealtime/)
assert.doesNotMatch(app, /quoteRequestVersion/)

function deferred() {
  let resolve
  let reject
  const promise = new Promise((yes, no) => { resolve = yes; reject = no })
  return { promise, resolve, reject }
}

let quotes = {}
const calls = []
const coordinator = createQuoteCoordinator({
  readQuotes: () => quotes,
  writeQuotes: next => { quotes = next },
  fetchQuote: code => {
    const call = { code, ...deferred() }
    calls.push(call)
    return call.promise
  },
})

// The watchlist contains stocks on three exchanges. A click must not wait for
// all prior list quote requests or accept an older response for that stock.
const items = [{ code: 'SZ.002315' }, { code: 'HK.00772' }, { code: 'US.ORCL' }]
const batch = coordinator.refreshList(items, 'SZ.002315')
assert.deepEqual(Object.keys(quotes).sort(), items.map(item => item.code).sort())
assert.equal(calls.length, 3)
const selected = coordinator.refresh('US.ORCL')
assert.equal(quotes['US.ORCL'].status, 'loading')
assert.equal(calls.length, 4)

calls[3].resolve({ code: 'US.ORCL', price: 101 })
await selected
assert.equal(quotes['US.ORCL'].data.price, 101)
assert.equal(quotes['SZ.002315'].status, 'loading')
calls[2].resolve({ code: 'US.ORCL', price: 99 })
calls[0].resolve({ code: 'SZ.002315', price: 20 })
calls[1].resolve({ code: 'HK.00772', price: 35 })
await batch
assert.equal(quotes['US.ORCL'].data.price, 101, 'old list response must not overwrite selected quote')
assert.equal(quotes['SZ.002315'].data.code, 'SZ.002315')
assert.equal(quotes['HK.00772'].data.code, 'HK.00772')

// Switching quickly back and forth keeps the newest response for each code.
const first = coordinator.refresh('SZ.002315')
const second = coordinator.refresh('US.ORCL')
const third = coordinator.refresh('SZ.002315')
calls[4].resolve({ code: 'SZ.002315', price: 21 })
calls[5].resolve({ code: 'US.ORCL', price: 102 })
calls[6].resolve({ code: 'SZ.002315', price: 22 })
await Promise.all([first, second, third])
assert.equal(quotes['SZ.002315'].data.price, 22)
assert.equal(quotes['US.ORCL'].data.price, 102)

// A provider returning a different security code must never be shown under
// the selected code.
const wrong = coordinator.refresh('US.ORCL')
calls[7].resolve({ code: 'SZ.002315', price: 1000 })
await wrong
assert.equal(quotes['US.ORCL'].status, 'error')
assert.match(quotes['US.ORCL'].error, /证券代码/)

// A late response for a stock removed from the displayed list must not
// re-introduce stale quotes.
const removed = coordinator.refresh('HK.00772')
const narrowed = coordinator.refreshList([{ code: 'US.ORCL' }], 'US.ORCL')
assert.deepEqual(Object.keys(quotes), ['US.ORCL'])
calls[8].resolve({ code: 'HK.00772', price: 36 })
calls[9].resolve({ code: 'US.ORCL', price: 103 })
await Promise.all([removed, narrowed])
assert.deepEqual(Object.keys(quotes), ['US.ORCL'])
assert.equal(quotes['US.ORCL'].data.price, 103)

// Signing out/unmounting prevents in-flight requests from repopulating data.
const duringLogout = coordinator.refresh('US.ORCL')
coordinator.reset()
quotes = {}
calls[10].resolve({ code: 'US.ORCL', price: 104 })
await duringLogout
assert.deepEqual(quotes, {})

console.log('V1.1.10 cross-market quote selection and stale-response protection: PASS')
