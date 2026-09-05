import assert from 'node:assert/strict'
import { createRealtimeUiBuffer, REALTIME_UI_FLUSH_MS } from './realtimeUiBuffer.mjs'

const timers = []
const flushed = []
let paused = false
const buffer = createRealtimeUiBuffer({
  flushMs: REALTIME_UI_FLUSH_MS,
  isPaused: () => paused,
  setTimeoutFn: callback => {
    timers.push(callback)
    return timers.length - 1
  },
  clearTimeoutFn: () => {},
  onFlush: payload => flushed.push(payload),
})

for (let revision = 1; revision <= 100; revision += 1) {
  buffer.push({ revision })
}
assert.equal(timers.length, 1)
timers.shift()()
assert.equal(flushed.length, 1)
assert.equal(flushed[0].revision, 100)
assert.equal(buffer.getFlushCount(), 1)

paused = true
buffer.push({ revision: 101 })
assert.equal(buffer.pending().revision, 101)
assert.equal(buffer.flush(), false)
paused = false
assert.equal(buffer.flush(), true)
assert.equal(flushed.at(-1).revision, 101)

console.log('realtime UI buffer coalescing: 100 events -> 2 flushes')
