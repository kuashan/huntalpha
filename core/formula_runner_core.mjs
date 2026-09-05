import { compileTongdaxinFormulaExpanded as compileFormula } from '../frontend/src/indicators/tongdaxinFormula.js'
import { calculateChipDistribution as defaultCalculateChipDistribution } from './chip_distribution.mjs'
import { formulaUsesChipFunctions } from './formula_dependencies.mjs'

const valueAt = (values, index) => Array.isArray(values) ? values[index] : values
const finite = value => typeof value === 'number' && Number.isFinite(value)

function adapt(result) {
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

export function runFormulaRequest(request, calculateChipDistribution = defaultCalculateChipDistribution) {
  if (!Array.isArray(request.bars) || !request.bars.length) throw new Error('公式计算缺少K线数据')
  const chips = formulaUsesChipFunctions(request.source)
    ? calculateChipDistribution(request.bars, request.chip)
    : (request.chip || {})
  const result = compileFormula(request.source, request.bars, chips, {
    period: request.period,
    symbol: request.symbol,
    name: request.name,
  })
  return { ...adapt(result), engine: 'tdx-server-v2' }
}
