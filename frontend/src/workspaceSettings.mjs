// Durable account-global chart settings contain only public indicator IDs and sizes.
export function restoreIndicatorItems(workspace, catalog) {
  const available = new Map((Array.isArray(catalog) ? catalog : [])
    .filter(item => item?.allowed !== false && item?.enabled !== false)
    .map(item => [item.code, item]))
  function restore(codes, placement, cap) {
    const seen = new Set()
    return (Array.isArray(codes) ? codes : []).flatMap(code => {
      const item = available.get(code)
      if (!item || item.placement !== placement || seen.has(code) || seen.size >= cap) return []
      seen.add(code)
      return [item]
    })
  }
  const main = restore(workspace?.main, 'main', 32)
  const sub = restore(workspace?.sub, 'sub', 3)
  const paneHeights = {}
  for (const item of sub) {
    const height = workspace?.pane_heights?.[item.code]
    if (Number.isInteger(height) && height >= 90 && height <= 800) paneHeights[item.code] = height
  }
  return { main, sub, paneHeights }
}

export function workspacePayload(main, sub, paneHeights) {
  const mainCodes = (Array.isArray(main) ? main : []).map(item => item.code)
  const subCodes = (Array.isArray(sub) ? sub : []).map(item => item.code)
  const heights = {}
  for (const code of subCodes) {
    const height = paneHeights?.[code]
    if (Number.isInteger(height) && height >= 90 && height <= 800) heights[code] = height
  }
  return { main: mainCodes, sub: subCodes, pane_heights: heights }
}
