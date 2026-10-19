import { strict as assert } from 'node:assert'
import { restoreIndicatorItems, workspacePayload } from './workspaceSettings.mjs'

const catalog = [
  { code: 'MA', placement: 'main', allowed: true, common: true },
  { code: 'CHANLUN', placement: 'main', allowed: true },
  { code: 'XMA', placement: 'main', allowed: false },
  { code: 'MACD', placement: 'sub', allowed: true },
  { code: 'RSI', placement: 'sub', allowed: true },
]
const saved = { main: ['MA', 'XMA', 'CHANLUN', 'MA'], sub: ['MACD', 'RSI'], pane_heights: { MACD: 180, RSI: 120, XMA: 300 } }
const restored = restoreIndicatorItems(saved, catalog)
assert.deepEqual(restored.main.map(item => item.code), ['MA', 'CHANLUN'])
assert.deepEqual(restored.sub.map(item => item.code), ['MACD', 'RSI'])
assert.deepEqual(restored.paneHeights, { MACD: 180, RSI: 120 })
assert.deepEqual(workspacePayload(restored.main, restored.sub, restored.paneHeights), {
  main: ['MA', 'CHANLUN'], sub: ['MACD', 'RSI'], pane_heights: { MACD: 180, RSI: 120 },
})
assert.deepEqual(restoreIndicatorItems({ main: [], sub: [], pane_heights: {} }, catalog).main, [])
const revoked = restoreIndicatorItems(saved, catalog.map(item => ({ ...item, allowed: item.code === 'MA' || item.code === 'MACD' })))
assert.deepEqual(revoked.main.map(item => item.code), ['MA'])
assert.deepEqual(revoked.sub.map(item => item.code), ['MACD'])
assert.deepEqual(workspacePayload([], [], { MACD: 180 }), { main: [], sub: [], pane_heights: {} })
console.log('account workspace frontend contracts: PASS')
