// Pure workspace mapping: no candles, market prices, formula source or localStorage.
export function restoreIndicatorWorkspace(workspace, catalog) {
  const available = new Map((Array.isArray(catalog) ? catalog : [])
    .filter(item => item.allowed !== false).map(item => [item.code, item]))
  const main = (workspace?.main || []).map(code => available.get(code))
    .filter(item => item?.placement === 'main')
  const sub = (workspace?.sub || []).map(code => available.get(code))
    .filter(item => item?.placement === 'sub').slice(0, 3)
  const heights = Object.fromEntries(sub
    .filter(item => Number.isInteger(workspace?.heights?.[item.code])
      && workspace.heights[item.code] >= 80 && workspace.heights[item.code] <= 800)
    .map(item => [item.code, workspace.heights[item.code]]))
  return { main, sub, heights }
}

export function snapshotIndicatorWorkspace(main, sub, heights) {
  const subCodes = sub.map(item => item.code).slice(0, 3)
  return {
    main: main.map(item => item.code),
    sub: subCodes,
    heights: Object.fromEntries(subCodes
      .filter(code => Number.isInteger(heights?.[code]))
      .map(code => [code, Math.max(80, Math.min(800, heights[code]))])),
  }
}
