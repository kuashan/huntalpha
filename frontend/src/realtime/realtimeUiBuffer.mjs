export const REALTIME_UI_FLUSH_MS = 300

const barFields = ['time', 'open', 'high', 'low', 'close', 'volume', 'amount', 'turnover_rate', 'is_closed']

function barFingerprint(bar) {
  return JSON.stringify(barFields.map(field => bar?.[field] ?? null))
}

export function mergeRealtimePayload(loadedBars, payload) {
  const byTime = new Map((loadedBars || []).map(bar => [Number(bar.time), bar]))
  const closedBar = payload?.last_closed_bar
  const currentBar = payload?.bar
  const previousClosed = Number.isFinite(Number(closedBar?.time)) ? byTime.get(Number(closedBar.time)) : undefined
  const previousCurrent = Number.isFinite(Number(currentBar?.time)) ? byTime.get(Number(currentBar.time)) : undefined
  for (const candidate of [closedBar, currentBar]) {
    const time = Number(candidate?.time)
    if (!Number.isFinite(time)) continue
    byTime.set(time, { ...(byTime.get(time) || {}), ...candidate, time })
  }
  return {
    bars: [...byTime.values()].sort((left, right) => Number(left.time) - Number(right.time)),
    closedChanged: Boolean(closedBar && (!previousClosed || barFingerprint(previousClosed) !== barFingerprint(closedBar))),
    currentChanged: Boolean(currentBar && (!previousCurrent || barFingerprint(previousCurrent) !== barFingerprint(currentBar))),
    closedBar: Number.isFinite(Number(closedBar?.time)) ? { ...closedBar, time: Number(closedBar.time) } : null,
    currentBar: Number.isFinite(Number(currentBar?.time)) ? { ...currentBar, time: Number(currentBar.time) } : null,
  }
}

export function mergeRealtimeBars(loadedBars, payload) {
  return mergeRealtimePayload(loadedBars, payload).bars
}

export function mergeHistoricalTail(loadedBars, tailBars, realtimePayload = null) {
  const before = [...(loadedBars || [])].sort((left, right) => Number(left.time) - Number(right.time))
  const byTime = new Map(before.map(bar => [Number(bar.time), bar]))
  for (const bar of tailBars || []) {
    const time = Number(bar?.time)
    if (Number.isFinite(time)) byTime.set(time, { ...bar, time })
  }
  for (const candidate of [realtimePayload?.last_closed_bar, realtimePayload?.bar]) {
    const time = Number(candidate?.time)
    if (Number.isFinite(time)) byTime.set(time, { ...(byTime.get(time) || {}), ...candidate, time })
  }
  const bars = [...byTime.values()].sort((left, right) => Number(left.time) - Number(right.time))
  const changed = bars.length !== before.length || bars.some((bar, index) => {
    const previous = before[index]
    return !previous || Number(previous.time) !== Number(bar.time) || barFingerprint(previous) !== barFingerprint(bar)
  })
  return { bars, changed }
}

export function createRealtimeUiBuffer({
  flushMs = REALTIME_UI_FLUSH_MS,
  onFlush,
  isPaused = () => false,
  setTimeoutFn = globalThis.setTimeout,
  clearTimeoutFn = globalThis.clearTimeout,
} = {}) {
  let latest = null
  let latestGeneration = 0
  let timer = null
  let flushCount = 0

  const flush = () => {
    timer = null
    if (isPaused() || latest === null) return false
    const payload = latest
    const generation = latestGeneration
    latest = null
    flushCount += 1
    onFlush?.(payload, generation)
    return true
  }

  const schedule = () => {
    if (timer !== null || isPaused()) return
    timer = setTimeoutFn(flush, flushMs)
  }

  return {
    push(payload, generation = 0) {
      latest = payload
      latestGeneration = generation
      schedule()
    },
    flush,
    clear() {
      if (timer !== null) clearTimeoutFn(timer)
      timer = null
      latest = null
      latestGeneration = 0
    },
    pause() {
      if (timer !== null) clearTimeoutFn(timer)
      timer = null
    },
    pending() {
      return latest
    },
    pendingGeneration() {
      return latest === null ? null : latestGeneration
    },
    getFlushCount() {
      return flushCount
    },
  }
}
