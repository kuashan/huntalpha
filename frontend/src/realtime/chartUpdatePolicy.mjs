function symbolCode(symbol) {
  return String(symbol?.code || '').toUpperCase()
}

function indicatorCodes(indicators) {
  return (Array.isArray(indicators) ? indicators : [])
    .map(item => String(item?.code || '').toUpperCase())
    .sort()
}

export function classifyChartUpdate(previous, next) {
  if (symbolCode(previous?.symbol) !== symbolCode(next?.symbol) || previous?.period !== next?.period) return 'full'
  const before = indicatorCodes(previous?.indicators)
  const after = indicatorCodes(next?.indicators)
  return before.length === after.length && before.every((code, index) => code === after[index]) ? 'none' : 'indicators'
}
