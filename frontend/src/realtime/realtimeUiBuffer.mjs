export const REALTIME_UI_FLUSH_MS = 300

export function createRealtimeUiBuffer({
  flushMs = REALTIME_UI_FLUSH_MS,
  onFlush,
  isPaused = () => false,
  setTimeoutFn = globalThis.setTimeout,
  clearTimeoutFn = globalThis.clearTimeout,
} = {}) {
  let latest = null
  let timer = null
  let flushCount = 0

  const flush = () => {
    timer = null
    if (isPaused() || latest === null) return false
    const payload = latest
    latest = null
    flushCount += 1
    onFlush?.(payload)
    return true
  }

  const schedule = () => {
    if (timer !== null || isPaused()) return
    timer = setTimeoutFn(flush, flushMs)
  }

  return {
    push(payload) {
      latest = payload
      schedule()
    },
    flush,
    clear() {
      if (timer !== null) clearTimeoutFn(timer)
      timer = null
      latest = null
    },
    pause() {
      if (timer !== null) clearTimeoutFn(timer)
      timer = null
    },
    pending() {
      return latest
    },
    getFlushCount() {
      return flushCount
    },
  }
}
