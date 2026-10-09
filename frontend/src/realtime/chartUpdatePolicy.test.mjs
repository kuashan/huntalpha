import assert from 'node:assert/strict'
import { classifyChartUpdate } from './chartUpdatePolicy.mjs'

const symbol = { code: 'SH.600519' }
const period = '日线'
const baseIndicators = [{ code: 'MA', placement: 'main', common: true }]

assert.equal(
  classifyChartUpdate({ symbol, period, indicators: baseIndicators }, { symbol, period, indicators: [...baseIndicators, { code: 'CHANLUN', placement: 'main' }] }),
  'indicators',
)
assert.equal(
  classifyChartUpdate({ symbol, period, indicators: baseIndicators }, { symbol: { code: 'HK.00700' }, period, indicators: baseIndicators }),
  'full',
)
assert.equal(
  classifyChartUpdate({ symbol, period, indicators: baseIndicators }, { symbol, period: '周线', indicators: baseIndicators }),
  'full',
)
