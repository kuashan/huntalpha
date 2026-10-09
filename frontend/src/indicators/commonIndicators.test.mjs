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

for (const code of codes) {
  const history = bars.slice(0, -1)
  const updates = [
    { ...bars.at(-1), close: 110, high: 112, low: 108, volume: 1_100 },
    { ...bars.at(-1), close: 111, high: 113, low: 107, volume: 1_150 },
    { ...bars.at(-1), close: 109.5, high: 114, low: 106, volume: 1_200 },
  ]
  let realtimeDrawing = commonDrawing(code, [...history, updates[0]])
  for (const update of updates.slice(1)) realtimeDrawing = commonDrawing(code, [...history, update])
  const fullDrawing = commonDrawing(code, [...history, updates.at(-1)])
  assert.deepEqual(comparable(realtimeDrawing), comparable(fullDrawing), `${code} same-bar update mismatch`)
}

console.log('common indicator realtime/full consistency: append 6/6, same-bar update 6/6 passed')
