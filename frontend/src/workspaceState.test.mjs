import assert from 'node:assert/strict'
import { restoreIndicatorWorkspace, snapshotIndicatorWorkspace } from './workspaceState.mjs'

const catalog = [
  { code: 'MA', placement: 'main', allowed: true },
  { code: 'MACD', placement: 'sub', allowed: true },
  { code: 'RSI', placement: 'sub', allowed: true },
  { code: 'XMA', placement: 'main', allowed: false },
]
const restored = restoreIndicatorWorkspace(
  { main: ['XMA', 'MA'], sub: ['MACD', 'RSI'], heights: { MACD: 180, RSI: 120 } }, catalog)
assert.deepEqual(restored.main.map(item => item.code), ['MA'])
assert.deepEqual(restored.sub.map(item => item.code), ['MACD', 'RSI'])
assert.deepEqual(snapshotIndicatorWorkspace(restored.main, restored.sub, restored.heights),
  { main: ['MA'], sub: ['MACD', 'RSI'], heights: { MACD: 180, RSI: 120 } })
assert.deepEqual(snapshotIndicatorWorkspace([], [], { MACD: 200 }),
  { main: [], sub: [], heights: {} })
assert.deepEqual(restoreIndicatorWorkspace({ main: [], sub: [], heights: {} }, []),
  { main: [], sub: [], heights: {} })
console.log('workspace state: PASS')
