// Only display preferences travel across devices: no market bars or formula source.
export function hydrateWorkspace(saved, catalog) {
  const permitted = new Map(
    (Array.isArray(catalog) ? catalog : []).filter(item => item.allowed !== false)
      .map(item => [item.code, item]),
  )
  const resolve = (codes, placement, limit) => {
    const seen = new Set()
    return (Array.isArray(codes) ? codes : [])
      .filter(code => {
        const item = permitted.get(code)
        if (!item || item.placement !== placement || seen.has(code)) return false
        seen.add(code)
        return true
      }).slice(0, limit).map(code => permitted.get(code))
  }
  const main = resolve(saved?.main, 'main', 64)
  const sub = resolve(saved?.sub, 'sub', 3)
  const paneHeights = {}
  for (const item of sub) {
    const height = saved?.pane_heights?.[item.code]
    if (Number.isInteger(height) && height >= 60 && height <= 2000) paneHeights[item.code] = height
  }
  return { main, sub, paneHeights }
}

export function serializeWorkspace(main, sub, paneHeights) {
  const activeSub = sub.map(item => item.code)
  const heights = {}
  for (const code of activeSub) {
    const height = paneHeights[code]
    if (Number.isInteger(height) && height >= 60 && height <= 2000) heights[code] = height
  }
  return {
    main: main.map(item => item.code),
    sub: activeSub,
    pane_heights: heights,
  }
}
