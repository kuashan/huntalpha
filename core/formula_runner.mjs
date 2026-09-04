import { readFileSync } from 'node:fs'
import { compileTongdaxinFormulaExpanded as compileFormula } from '../frontend/src/indicators/tongdaxinFormula.js'
import { calculateChipDistribution } from './chip_distribution.mjs'

// This short-lived server process is the only place where private formula
// source is parsed. The browser receives drawing coordinates, never source.
function adapt(result) {
  const valueAt = (values, index) => Array.isArray(values) ? values[index] : values
  const finite = value => typeof value === 'number' && Number.isFinite(value)
  return {
    lines: result.lines || [],
    sticks: (result.sticks || []).map(row => ({
      color: row.color || '#f8fafc',
      layer: row.layer || 'normal',
      points: (row.condition || []).flatMap((condition, index) => {
        const from = valueAt(row.from, index)
        const value = valueAt(row.to, index)
        return condition && finite(from) && finite(value) ? [{
          barIndex: index,
          from,
          to: value,
          width: valueAt(row.width, index),
          empty: valueAt(row.empty, index),
        }] : []
      }),
    })).filter(row => row.points.length),
    markers: (result.markers || []).flatMap(row => (row.condition || []).flatMap((condition, index) => {
      const value = valueAt(row.value, index)
      const markerText = valueAt(row.text, index)
      return condition && finite(value) ? [{
        color: row.color || '#f8fafc',
        text: markerText === undefined ? '' : String(markerText),
        barIndex: index,
        value,
      }] : []
    })),
    fixedTexts: result.fixedTexts || [],
  }
}

try {
  const request = JSON.parse(readFileSync(0, 'utf8'))
  if (!Array.isArray(request.bars) || !request.bars.length) throw new Error('公式计算缺少K线数据')
  const chips = calculateChipDistribution(request.bars, request.chip)
  const result = compileFormula(request.source, request.bars, chips, {
    period: request.period,
    symbol: request.symbol,
    name: request.name,
  })
  process.stdout.write(JSON.stringify({ ...adapt(result), engine: 'tdx-server-v2' }))
} catch (error) {
  process.stderr.write(error instanceof Error ? error.message : String(error))
  process.exitCode = 1
}
