import assert from 'node:assert/strict'
import { createChartTimeFormatters } from './chartTimeFormat.mjs'

const chinaOpenUtc = Date.parse('2026-10-19T01:30:00Z') / 1000
const daily = createChartTimeFormatters('日线', 'Asia/Shanghai')
assert.equal(daily.timeVisible, false)
assert.equal(daily.tickMarkFormatter(chinaOpenUtc, 3), '10/19')
assert.equal(daily.timeFormatter(chinaOpenUtc), '2026-10-19')
assert.equal(createChartTimeFormatters('周线', 'Asia/Shanghai').timeVisible, false)
assert.equal(createChartTimeFormatters('月线', 'Asia/Shanghai').timeFormatter(chinaOpenUtc), '2026-10-19')

const minute = createChartTimeFormatters('1分', 'Asia/Shanghai')
assert.equal(minute.timeVisible, true)
assert.equal(minute.tickMarkFormatter(chinaOpenUtc, 3), '09:30')
assert.equal(minute.timeFormatter(chinaOpenUtc), '2026-10-19 09:30')
assert.equal(minute.tickMarkFormatter(chinaOpenUtc, 2), '10/19')
assert.equal(minute.tickMarkFormatter(chinaOpenUtc, 0), '2026')

const ny = createChartTimeFormatters('60分', 'America/New_York')
assert.equal(ny.timeFormatter(Date.parse('2026-03-09T13:30:00Z') / 1000), '2026-03-09 09:30')
assert.equal(ny.timeFormatter(Date.parse('2026-11-02T14:30:00Z') / 1000), '2026-11-02 09:30')
assert.equal(chinaOpenUtc, Date.parse('2026-10-19T01:30:00Z') / 1000) // The timestamp was never shifted.
console.log('Chart calendar/timezone formatting: PASS')
