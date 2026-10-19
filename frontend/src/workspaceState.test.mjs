import assert from 'node:assert/strict'
import { hydrateWorkspace, serializeWorkspace } from './workspaceState.mjs'

const catalog = [
  { code: 'MA', placement: 'main', name: 'MA', allowed: true },
  { code: 'SSSS', placement: 'main', name: 'private formula', allowed: false },
  { code: 'MACD', placement: 'sub', name: 'MACD', allowed: true },
  { code: 'RSI', placement: 'sub', name: 'RSI', allowed: true },
  { code: 'KDJ', placement: 'sub', name: 'KDJ', allowed: true },
  { code: 'VOL', placement: 'sub', name: 'VOL', allowed: true },
]
const saved = {
  main: ['SSSS', 'MA', 'MA'], sub: ['MACD', 'RSI', 'KDJ', 'VOL'],
  pane_heights: { MACD: 180, RSI: 120, SSSS: 300, VOL: 200 },
}
const restored = hydrateWorkspace(saved, catalog)
assert.deepEqual(restored.main.map(item => item.code), ['MA'])
assert.deepEqual(restored.sub.map(item => item.code), ['MACD', 'RSI', 'KDJ'])
assert.deepEqual(restored.paneHeights, { MACD: 180, RSI: 120 })
assert.deepEqual(serializeWorkspace(restored.main, restored.sub, restored.paneHeights), {
  main: ['MA'], sub: ['MACD', 'RSI', 'KDJ'], pane_heights: { MACD: 180, RSI: 120 },
})
assert.deepEqual(hydrateWorkspace({}, catalog), { main: [], sub: [], paneHeights: {} })
assert.deepEqual(serializeWorkspace([], [], {}), { main: [], sub: [], pane_heights: {} })
console.log('Task 005.2 workspace hydration and serialization: PASS')
