import assert from 'node:assert/strict'
import { classifyChartUpdate, diffIndicatorSets } from './chartUpdatePolicy.mjs'

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

const withMacd = [...baseIndicators, { code: 'MACD', placement: 'sub', common: true }]
const diff = diffIndicatorSets(baseIndicators, withMacd)
assert.deepEqual(diff.added.map(item => item.code), ['MACD'])
assert.deepEqual(diff.removed, [])
assert.deepEqual(diff.retained.map(item => item.code), ['MA'])

const changedPlacement = diffIndicatorSets(baseIndicators, [{ ...baseIndicators[0], placement: 'sub' }])
assert.deepEqual(changedPlacement.added.map(item => item.placement), ['sub'])
assert.deepEqual(changedPlacement.removed.map(item => item.placement), ['main'])
assert.deepEqual(changedPlacement.retained, [])
assert.equal(
  classifyChartUpdate({ symbol, period, indicators: baseIndicators }, { symbol, period: '周线', indicators: baseIndicators }),
  'full',
)
