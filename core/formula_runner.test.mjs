import assert from 'node:assert/strict'
import test from 'node:test'

import { calculateChipDistribution } from './chip_distribution.mjs'
import { formulaUsesChipFunctions } from './formula_dependencies.mjs'
import { runFormulaRequest } from './formula_runner_core.mjs'

function makeBars(count) {
  return Array.from({ length: count }, (_, index) => ({
    time: 1_700_000_000 + index * 86_400,
    open: 10 + index * 0.01,
    high: 11 + index * 0.01,
    low: 9 + index * 0.01,
    close: 10.2 + index * 0.01,
    volume: 100_000 + index,
    amount: (100_000 + index) * (10.1 + index * 0.01),
    turnover_rate: 1,
  }))
}

function makeChipPayload(count) {
  return {
    floatShares: 100_000,
    costs: Object.fromEntries(Array.from({ length: 101 }, (_, percentage) => [percentage, Array(count).fill(10 + percentage / 100)])),
    winners: Array(count).fill(0.5),
  }
}

test('non-chip formulas skip chip calculation completely', () => {
  let calls = 0
  const result = runFormulaRequest({
    source: 'OUT:MA(C,3);',
    bars: makeBars(8),
    period: '日线',
    symbol: 'SH.600519',
    name: 'synthetic',
    chip: { floatShares: 1000 },
  }, () => {
    calls += 1
    throw new Error('chip calculation should be skipped')
  })

  assert.equal(calls, 0)
  assert.equal(result.engine, 'tdx-server-v2')
})

test('comments, strings, and ordinary identifiers do not create chip dependencies', () => {
  assert.equal(formulaUsesChipFunctions('{ COST(50) } OUT:C;'), false)
  assert.equal(formulaUsesChipFunctions('// WINNER(C)\nOUT:C;'), false)
  assert.equal(formulaUsesChipFunctions('/* LWINNER(C) */ OUT:C;'), false)
  assert.equal(formulaUsesChipFunctions('LABEL:"WINNER(50)"; OUT:C;'), false)
  assert.equal(formulaUsesChipFunctions('COSTUME:C;'), false)
  assert.equal(formulaUsesChipFunctions('OUT:COSTUME(C);'), false)
})

test('COST, WINNER, and LWINNER calls enable chip calculation', () => {
  for (const functionName of ['COST', 'WINNER', 'LWINNER']) {
    let calls = 0
    const result = runFormulaRequest({
      source: `OUT:${functionName}(50);`,
      bars: makeBars(8),
      period: '日线',
      symbol: 'SH.600519',
      name: 'synthetic',
    }, count => {
      calls += 1
      assert.equal(count.length, 8)
      return makeChipPayload(8)
    })

    assert.equal(calls, 1)
    assert.equal(result.engine, 'tdx-server-v2')
  }
})

test('optimized chip distribution matches the deterministic baseline', () => {
  const bars = [
    { low: 10, high: 11, close: 10.5, volume: 100, amount: 1025, turnover_rate: 100 },
    { low: 10, high: 12, close: 11, volume: 100, amount: 1125, turnover_rate: 50 },
    { low: 9, high: 13, close: 12, volume: 100, amount: 1200, turnover_rate: 25 },
    { low: 9, high: 14, close: 13, volume: 100, amount: 1300, turnover_rate: 10 },
  ]
  const result = calculateChipDistribution(bars, { floatShares: 1000 })
  const percentages = [0, 25, 50, 75, 100]
  const expectedCosts = [
    [10.005, 10.005, 9.005, 9.005],
    [10.245, 10.355, 10.385, 10.405],
    [10.385, 10.645, 10.765, 10.835],
    [10.565, 11.115, 11.325, 11.455],
    [10.995, 12.005, 12.995, 13.995],
  ]
  percentages.forEach((percentage, row) => {
    result.costs[percentage].forEach((actual, index) => {
      assert.ok(Math.abs(actual - expectedCosts[row][index]) < 1e-12)
    })
  })
  ;[2 / 3, 0.7, 0.9375, 0.98].forEach((expected, index) => {
    assert.ok(Math.abs(result.winners[index] - expected) < 1e-12)
  })
})

test('1200-bar regression sorts at most once per bar', () => {
  let sortCalls = 0
  const result = calculateChipDistribution(makeBars(1200), { floatShares: 100_000_000 }, { onSort: () => { sortCalls += 1 } })

  assert.equal(sortCalls, 1200)
  assert.equal(result.costs[0].length, 1200)
  assert.equal(result.costs[100].length, 1200)
  assert.equal(result.winners.length, 1200)
})
