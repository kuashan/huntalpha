import assert from 'node:assert/strict'
import { hasChangedBarSource } from './sourceSwitch.mjs'

assert.equal(hasChangedBarSource('yahoo-finance', { bar: { provider: 'tencent-public', time: 1 } }), true)
assert.equal(hasChangedBarSource('tencent-public', { bar: { provider: 'yahoo-finance', time: 1 } }), true)
assert.equal(hasChangedBarSource('longbridge', { bar: { provider: 'longbridge', time: 1 } }), false)
assert.equal(hasChangedBarSource('coinbase', { bar: { provider: 'coinbase', time: 1 } }), false)
assert.equal(hasChangedBarSource('yahoo-finance', { source: 'public-market', status: 'polling' }), false)
assert.equal(hasChangedBarSource('', { bar: { provider: 'tencent-public', time: 1 } }), false)
console.log('market-source switch: PASS')
