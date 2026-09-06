import assert from 'node:assert/strict'
import { commonDrawing } from './commonIndicators.js'

const bars = Array.from({ length: 48 }, (_, index) => {
  const close = 100 + Math.sin(index / 3) * 4 + index * 0.2
  return {
    time: 1_700_000_000 + index * 60,
    open: close - 0.7,
    high: close + 1.4,
    low: close - 1.2,
    close,
    volume: 1_000 + index * 13,
  }
})

const codes = ['MA', 'BOLL', 'VOL', 'MACD', 'KDJ', 'RSI']
const comparable = drawing => ({
  lines: drawing.lines.map(line => line.data.map(point => [point.time, point.value])),
  sticks: drawing.sticks.map(group => group.data.map(point => [point.time, point.from, point.to])),
})

for (const code of codes) {
  let realtimeBars = bars.slice(0, 20)
  let realtimeDrawing = commonDrawing(code, realtimeBars)
  for (const bar of bars.slice(20)) {
    realtimeBars = [...realtimeBars, bar]
    realtimeDrawing = commonDrawing(code, realtimeBars)
  }
  const fullDrawing = commonDrawing(code, bars)
  assert.deepEqual(comparable(realtimeDrawing), comparable(fullDrawing), `${code} realtime/full mismatch`)
}

console.log('common indicator realtime/full consistency: 6/6 passed')
