import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { createRealtimeUiBuffer, mergeHistoricalTail, mergeRealtimeBars, mergeRealtimePayload, REALTIME_UI_FLUSH_MS } from './realtimeUiBuffer.mjs'
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
assert.equal(staleSameGeneration.reason, 'stale_revision')
assert.equal(reconcileRealtimeVersion('epoch-b', 5, { epoch: 'epoch-b', revision: 4 }).reason, 'stale_revision')
assert.equal(isFormulaResponseGenerationSafe('epoch-b', 'epoch-a', 'epoch-a'), false)
assert.equal(isFormulaResponseGenerationSafe('epoch-a', 'epoch-a', 'epoch-b'), true)

let statusWatermark = { epoch: 'epoch-a', revision: 9, status: 'live' }
const acceptStatus = payload => {
  const decision = reconcileRealtimeVersion(statusWatermark.epoch, statusWatermark.revision, payload)
  if (decision.accepted) {
    statusWatermark = { epoch: decision.epoch, revision: decision.revision, status: payload.status }
  }
  return decision
}
assert.equal(acceptStatus({ epoch: 'epoch-a', revision: 10, status: 'reconnecting' }).accepted, true)
assert.deepEqual(statusWatermark, { epoch: 'epoch-a', revision: 10, status: 'reconnecting' })
assert.equal(acceptStatus({ epoch: 'epoch-a', revision: 9, status: 'live' }).reason, 'stale_revision')
assert.deepEqual(statusWatermark, { epoch: 'epoch-a', revision: 10, status: 'reconnecting' })
assert.equal(acceptStatus({ epoch: 'epoch-a', revision: 11, status: 'live' }).accepted, true)
assert.deepEqual(statusWatermark, { epoch: 'epoch-a', revision: 11, status: 'live' })
assert.equal(acceptStatus({ epoch: 'epoch-c', revision: 1, status: 'reconnecting' }).accepted, true)
assert.deepEqual(statusWatermark, { epoch: 'epoch-c', revision: 1, status: 'reconnecting' })

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
const firstBoundary = mergeRealtimePayload(boundaryBars, boundaryPayload)
assert.equal(firstBoundary.closedChanged, true)
assert.equal(firstBoundary.currentChanged, true)
let repeatedFullSeriesUpdates = firstBoundary.closedChanged ? 1 : 0
let currentBars = firstBoundary.bars
for (let revision = 1; revision <= 50; revision += 1) {
  const next = mergeRealtimePayload(currentBars, {
    last_closed_bar: { time: 100, close: 100.5, volume: 1000 },
    bar: { time: 101, close: 101 + revision / 100, volume: 20 + revision },
  })
  if (next.closedChanged) repeatedFullSeriesUpdates += 1
  currentBars = next.bars
}
assert.equal(repeatedFullSeriesUpdates, 1)
assert.equal(currentBars.at(-1).time, 101)

const historicalTail = mergeHistoricalTail(
  [{ time: 1, close: 1 }, { time: 90, close: 90 }, { time: 95, close: 95 }, { time: 100, close: 100 }],
  Array.from({ length: 21 }, (_, index) => ({ time: 90 + index, close: 90 + index + (index === 5 ? 0.5 : 0) })),
  { bar: { time: 110, close: 111 } },
)
assert.equal(historicalTail.changed, true)
assert.deepEqual(historicalTail.bars.map(bar => bar.time), [1, ...Array.from({ length: 21 }, (_, index) => 90 + index)])
assert.equal(historicalTail.bars.find(bar => bar.time === 95).close, 95.5)
assert.equal(historicalTail.bars.at(-1).close, 111)

const latestPayloadCorrection = mergeHistoricalTail(
  [{ time: 100, close: 100 }],
  [{ time: 100, close: 101 }],
  { bar: { time: 101, close: 102 } },
)
assert.equal(latestPayloadCorrection.bars.at(-1).close, 102)

const recovery = { needs: false, inFlight: false, retryTimer: false, status: 'live' }
const requestRecovery = () => {
  recovery.needs = true
  if (recovery.inFlight) return
  recovery.inFlight = true
  recovery.status = 'reconnecting'
}
const failRecovery = () => {
  recovery.inFlight = false
  recovery.needs = true
  recovery.retryTimer = true
  recovery.status = 'reconnecting'
}
const succeedRecovery = () => {
  recovery.inFlight = false
  recovery.needs = false
  recovery.retryTimer = false
  recovery.status = 'live'
}
requestRecovery()
failRecovery()
assert.deepEqual(recovery, { needs: true, inFlight: false, retryTimer: true, status: 'reconnecting' })
requestRecovery()
succeedRecovery()
assert.deepEqual(recovery, { needs: false, inFlight: false, retryTimer: false, status: 'live' })

let formulaRunToken = 1
const staleFormulaToken = formulaRunToken
formulaRunToken += 1
assert.notEqual(staleFormulaToken, formulaRunToken)

const marketChartSource = readFileSync(new URL('../components/MarketChart.vue', import.meta.url), 'utf8')
assert.match(marketChartSource, /needsHistoryReconcile/)
assert.match(marketChartSource, /HISTORY_RECONCILE_RETRY_MS = 2000/)
assert.match(marketChartSource, /Array\.isArray\(payload\.bars\)/)
const reconcileSource = marketChartSource.slice(
  marketChartSource.indexOf('async function reconcileHistoryTail'),
  marketChartSource.indexOf('function requestHistoryTailReconcile'),
)
assert.ok(reconcileSource.indexOf('cancelFormulaWork()') < reconcileSource.indexOf('queueFormulaRefresh'))

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
