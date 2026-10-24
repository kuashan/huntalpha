// A market-source switch must replace a whole window, not append to older
// provider candles that may use other timestamps, OHLCV or adjustment bases.
export function hasChangedBarSource(loadedSource, payload) {
  const next = payload?.bar?.provider || payload?.last_closed_bar?.provider
  return Boolean(loadedSource && next && next !== loadedSource)
}
