export const REALTIME_UI_FLUSH_MS = 300

export function mergeRealtimeBars(loadedBars, payload) {
  const byTime = new Map((loadedBars || []).map(bar => [Number(bar.time), bar]))
  for (const candidate of [payload?.last_closed_bar, payload?.bar]) {
    const time = Number(candidate?.time)
    if (!Number.isFinite(time)) continue
    byTime.set(time, { ...(byTime.get(time) || {}), ...candidate, time })
  }
  return [...byTime.values()].sort((left, right) => Number(left.time) - Number(right.time))
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
