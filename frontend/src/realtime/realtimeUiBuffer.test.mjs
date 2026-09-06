import assert from 'node:assert/strict'
import { createRealtimeUiBuffer, mergeRealtimeBars, REALTIME_UI_FLUSH_MS } from './realtimeUiBuffer.mjs'
import { isFormulaResponseGenerationSafe, reconcileRealtimeVersion } from './realtimeGeneration.mjs'

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

const restarted = reconcileRealtimeVersion('epoch-a', 500, { epoch: 'epoch-b', revision: 1 })
assert.equal(restarted.accepted, true)
assert.equal(restarted.epoch, 'epoch-b')
const staleSameGeneration = reconcileRealtimeVersion('epoch-b', 5, { epoch: 'epoch-b', revision: 4 })
assert.equal(staleSameGeneration.accepted, false)
assert.equal(isFormulaResponseGenerationSafe('epoch-b', 'epoch-a', 'epoch-a'), false)
assert.equal(isFormulaResponseGenerationSafe('epoch-a', 'epoch-a', 'epoch-b'), true)

const boundaryBars = [{ time: 100, close: 100, volume: 900 }]
const boundaryPayload = {
  last_closed_bar: { time: 100, close: 100.5, volume: 1000 },
  bar: { time: 101, close: 101, volume: 20 },
}
const boundaryResult = mergeRealtimeBars(boundaryBars, boundaryPayload)
assert.deepEqual(boundaryResult, [
  { time: 100, close: 100.5, volume: 1000 },
  { time: 101, close: 101, volume: 20 },
])

const staleBufferTimers = []
const staleFlushes = []
const staleBuffer = createRealtimeUiBuffer({
  setTimeoutFn: callback => { staleBufferTimers.push(callback); return staleBufferTimers.length - 1 },
  clearTimeoutFn: () => {},
  onFlush: (payload, generation) => staleFlushes.push({ payload, generation }),
})
staleBuffer.push({ status: 'live', revision: 9 }, 1)
staleBuffer.clear()
staleBuffer.push({ status: 'unavailable', revision: 10 }, 2)
staleBufferTimers.at(-1)()
assert.deepEqual(staleFlushes, [{ payload: { status: 'unavailable', revision: 10 }, generation: 2 }])

console.log('realtime UI buffer coalescing: 100 events -> 2 flushes')
