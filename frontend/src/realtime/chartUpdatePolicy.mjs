function symbolCode(symbol) {
  return String(symbol?.code || '').toUpperCase()
}

function indicatorCodes(indicators) {
  return (Array.isArray(indicators) ? indicators : [])
    .map(item => String(item?.code || '').toUpperCase())
    .sort()
}

export function indicatorKey(item) {
  return [
    String(item?.code || '').toUpperCase(),
    String(item?.version || 1),
    String(item?.placement || 'main'),
    item?.common ? 'common' : 'formula',
  ].join('|')
}

export function diffIndicatorSets(previous, next) {
  const before = Array.isArray(previous) ? previous : []
  const after = Array.isArray(next) ? next : []
  const beforeKeys = new Set(before.map(indicatorKey))
  const afterKeys = new Set(after.map(indicatorKey))
  return {
    added: after.filter(item => !beforeKeys.has(indicatorKey(item))),
    removed: before.filter(item => !afterKeys.has(indicatorKey(item))),
    retained: after.filter(item => beforeKeys.has(indicatorKey(item))),
  }
}

export function classifyChartUpdate(previous, next) {
  if (symbolCode(previous?.symbol) !== symbolCode(next?.symbol) || previous?.period !== next?.period) return 'full'
  const before = (Array.isArray(previous?.indicators) ? previous.indicators : []).map(indicatorKey).sort()
  const after = (Array.isArray(next?.indicators) ? next.indicators : []).map(indicatorKey).sort()
  return before.length === after.length && before.every((code, index) => code === after[index]) ? 'none' : 'indicators'
}
